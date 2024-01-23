"""This file may be distributed under the terms of the GNU GPLv3 license"""
import os
import shelve
import time
from threading import Thread, Lock
from typing import Union

_DB_NAME = "motion_minder.dbm"


class MotionMinder:
    """
    This plugin keeps track of the distance traveled by the toolhead.
    It works by decorating the toolhead.move function and keeping track of the
        position before the move. Moves executed by probing or homing are partially
        ignored, as part of the move do not completely follow de toolhead.move function.

    """

    def __init__(self, config):
        """
        
        :param config: The klippy config object.
        """
        self._config = config
        self._printer = config.get_printer()
        self._toolhead = None
        self._gcode = self._printer.lookup_object("gcode")
        self._steppers = {"x": None, "y": None, "z": None}
        self._position = {"x": 0, "y": 0, "z": 0}

        self._db_fname = self._printer.get_start_args().get("config_file", "")
        self._db_fname = os.path.split(self._db_fname)[0]
        self._db_fname = os.path.dirname(self._db_fname)  # go back 1 folder level
        self._db_fname = os.path.join(self._db_fname, "database", _DB_NAME)

        self._lock = Lock()
        self._update_db = False

        self._ignore_position = False

        with shelve.open(self._db_fname) as db:
            self._odometer = db.get("odometer", {"x": 0, "y": 0, "z": 0})

        self._printer.register_event_handler("klippy:mcu_identify", self._get_toolhead)
        self._printer.register_event_handler(
            "homing:homing_move_begin", self._home_begin
        )
        self._printer.register_event_handler("homing:homing_move_end", self._home_end)

        self._thread = Thread(target=self._motion_minder_thread)
        self._thread.daemon = True
        self._thread.start()

        self._gcode.register_command(
            "MOTION_MINDER",
            self._cmd_motion_minder,
            desc="Get/set odometer parameters.",
        )

    def _home_begin(self, *args, **kwargs) -> None:
        """
        This is called when the toolhead starts homing and sets a flag to ignore the
            position in our decorator.

        :param args: Keep compatibility with the event handler.
        :param kwargs: Keep compatibility with the event handler.
        :return:
        """
        self._ignore_position = True

    def _home_end(self, *args, **kwargs) -> None:
        """
        This is called when the toolhead finishes homing and clears the flag to
            ignore the position in our decorator.

        :param args: Keep compatibility with the event handler.
        :param kwargs: Keep compatibility with the event handler.
        :return:
        """
        self._ignore_position = False

    def _motion_minder_thread(self) -> None:
        """
        This thread is responsible for saving the odometer value to disk every 5 seconds.
            Its use thread in order to not block the main thread.

        :return:
        """
        while True:
            time.sleep(5)
            with self._lock:
                with shelve.open(self._db_fname) as db:
                    db["odometer"] = self._odometer
                    self._update_db = False

    def _decorate_move(self, func: callable) -> callable:
        """
        This decorator is used to keep track of the toolhead position.
            It decorates the toolhead.move function.

        :param func: The toolhead.move function.
        :return:
        """

        def wrapper(newpos: list, speed: Union[int, float]):
            for i, axis in enumerate("xyz"):
                if self._ignore_position:
                    break
                if newpos[i] != self._position[axis]:
                    self._odometer[axis] += abs(newpos[i] - self._position[axis])
                    self._position[axis] = newpos[i]
                    self._update_db = True
            return func(newpos, speed)

        return wrapper

    def _get_toolhead(self) -> None:
        """
        This is called when the toolhead is identified and decorates the toolhead.move function.
            As the toolhead is identified only after loading the klippy extras we need to
            register in the event handler that is called after the toolhead is loaded.

        :return:
        """
        self._toolhead = self._printer.lookup_object("toolhead")
        self._toolhead.move = self._decorate_move(self._toolhead.move)

    def _cmd_motion_minder(self, gcmd) -> None:
        """
        Our gcode command handler. This is called when the user sends a MOTION_MINDER command.

        :param gcmd: the gcode command provided by klippy.
        :return:
        """
        params = gcmd.get_command_parameters()
        for key in params:
            if key not in ["SET_ODOMETER", "SET_MAINTENANCE", "AXES", "UNIT"]:
                raise self._gcode.error(f"Invalid parameter '{key}'.")
            
        set_odometer = gcmd.get_float("SET_ODOMETER", None)
        set_maintenance = gcmd.get_float("SET_MAINTENANCE", None)
        axes = gcmd.get("AXES", "xyz")
        unit = gcmd.get("UNIT", "km")

        if set_odometer is None and set_maintenance is None:
            self._return_odometer()
        elif set_odometer is not None:
            self._set_odometer(set_odometer, axes, unit)
        elif set_maintenance is not None:
            self._set_maintenance(set_maintenance, axes, unit)

    @staticmethod
    def _get_recommended_unit(value: Union[int, float]) -> str:
        """
        Get the magnitude of the value and return the recommended unit.

        :param value: The value in mm.
        :return: The recommended unit. It can be 'mm', 'm' or 'km'.
        """
        if value < 1000:
            return "mm"
        elif value < 1000000:
            return "m"
        return "km"

    @staticmethod
    def _convert_mm_to_unit(value: Union[int, float], unit: str) -> Union[int, float]:
        """
        Convert the value from mm to the desired unit.

        :param value: The value in mm.
        :param unit: The desired unit. It can be 'mm', 'm' or 'km'.
        :return: The value in the desired unit.
        """
        if unit == "m":
            return value / 1000
        elif unit == "km":
            return value / 1000000
        return value

    @staticmethod
    def _convert_unit_to_mm(value: Union[int, float], unit: str) -> Union[int, float]:
        """
        Convert the value from the desired unit to mm.

        :param value: The value in the desired unit.
        :param unit: The desired unit. It can be 'mm', 'm' or 'km'.
        :return: The value in mm.
        """
        if unit == "m":
            return value * 1000
        elif unit == "km":
            return value * 1000000
        return value

    def _return_odometer(self) -> None:
        """
        Return the odometer value to the user.

        :return:
        """
        result = ""
        for axis in self._odometer:
            raw_value = self._odometer[axis]
            unit = self._get_recommended_unit(raw_value)
            value = self._convert_mm_to_unit(raw_value, unit)
            result += f"{axis.upper()}: {value:.3f} {unit}\n"
            with self._lock:
                with shelve.open(self._db_fname) as db:
                    next_maintenance = db.get(f"next_maintenance_{axis}", None)
                    if next_maintenance is not None and next_maintenance > raw_value:
                        unit = self._get_recommended_unit(next_maintenance - raw_value)
                        next_maintenance = self._convert_mm_to_unit(
                            next_maintenance - raw_value, unit
                        )
                        result += (
                            f"  Next maintenance in: {next_maintenance:.3f} {unit}\n"
                        )
                    elif next_maintenance is not None:
                        unit = self._get_recommended_unit(raw_value - next_maintenance)
                        next_maintenance = self._convert_mm_to_unit(
                            raw_value - next_maintenance, unit
                        )
                        result += f"  Maintenance due: {next_maintenance:.3f} {unit}\n"
                    else:
                        result += "  Maintenance not set.\n"
        self._gcode.respond_info(result)

    def _set_odometer(self, value: Union[int, float], axes: str, unit: str) -> None:
        """
        Set the odometer values.

        :param value: The value in the desired unit. It can be 'mm', 'm' or 'km'.
        :param axes: The axes to set. It can be 'x', 'y', 'z' or any combination of them.
        :param unit: The desired unit. It can be 'mm', 'm' or 'km'.
        :return:
        """
        if unit not in ["mm", "m", "km"]:
            raise self._gcode.error(f"Invalid unit '{unit}'.")

        value = self._convert_unit_to_mm(value, unit)
        for axis in axes.lower():
            if axis not in "xyz":
                raise self._gcode.error(f"Invalid '{axis}' axis.")
            self._odometer[axis] = value
            with self._lock:
                with shelve.open(self._db_fname) as db:
                    db[f"odometer_{axis}"] = value
        self._return_odometer()

    def _set_maintenance(self, value: Union[int, float], axes: str, unit: str):
        """
        Set the maintenance values.

        :param value: The value in the desired unit. It can be 'mm', 'm' or 'km'.
        :param axes: The axes to set. It can be 'x', 'y', 'z' or any combination of them.
        :param unit: The desired unit. It can be 'mm', 'm' or 'km'.
        :return:
        """
        if unit not in ["mm", "m", "km"]:
            raise self._gcode.error(f"Invalid unit '{unit}'.")

        value = self._convert_unit_to_mm(value, unit)
        for axis in axes.lower():
            if axis not in "xyz":
                raise self._gcode.error(f"Invalid '{axis}' axis.")
            with self._lock:
                with shelve.open(self._db_fname) as db:
                    db[f"next_maintenance_{axis}"] = value + self._odometer[axis]
                    db[f"maintenance_{axis}"] = value


def load_config(config):
    """
    klippy calls this function to load the plugin.

    :param config:
    :return:
    """
    return MotionMinder(config)
