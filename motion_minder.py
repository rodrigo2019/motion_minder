"""This file may be distributed under the terms of the GNU GPLv3 license"""
import dbm
import dbm.dumb
import os
import shelve
import time
from threading import Thread, Lock
from typing import Union

_DB_NAME = "motion_minder"


class _Args:
    def __init__(self, gcmd, gcode):
        self._gcode = gcode
        params = gcmd.get_command_parameters()
        for key in params:
            if key not in ["SET_ODOMETER", "SET_MAINTENANCE", "AXES", "UNIT", "RELATIVE"]:
                raise self._gcode.error(f"Invalid parameter '{key}'.")

        self.set_odometer = gcmd.get_float("SET_ODOMETER", None)
        self.set_maintenance = gcmd.get_float("SET_MAINTENANCE", None)
        self.axes = gcmd.get("AXES", "xyz").lower()
        self.unit = gcmd.get("UNIT", None)
        self.unit = self.unit.lower() if self.unit is not None else None
        self.relative = gcmd.get("RELATIVE", False)

        self.validate()

    def validate(self):
        for attr_name in dir(self):
            if attr_name.startswith('val_') and callable(getattr(self, attr_name)):
                getattr(self, attr_name)()

    def val_set_odometer(self):
        if self.set_odometer is not None and self.set_maintenance is not None:
            raise self._gcode.error("Only one of 'SET_ODOMETER' or 'SET_MAINTENANCE' can be used.")

    def val_set_maintenance(self):
        if self.set_maintenance is not None and self.set_odometer is not None:
            raise self._gcode.error("Only one of 'SET_ODOMETER' or 'SET_MAINTENANCE' can be used.")

    def val_axes(self):
        for axis in self.axes:
            if axis not in "xyz":
                raise self._gcode.error(f"Invalid '{axis}' axis.")
        if len(self.axes) != len(set(self.axes)):
            raise self._gcode.error(f"Duplicate axes.")

    def val_unit(self):
        if self.unit not in ["mm", "m", "km", None]:
            raise self._gcode.error(f"Invalid unit '{self.unit}'. The valid units are 'mm', 'm' and 'km'.")

    def val_relative(self):
        true_values = ["true", "yes", "1"]
        false_values = ["false", "no", "0"]
        if isinstance(self.relative, str):
            if self.relative.lower() in true_values + false_values:
                self.relative = self.relative.lower() in true_values
            else:
                valid_values = ", ".join(true_values + false_values)
                raise self._gcode.error(
                    f"Invalid value '{self.relative}' for 'RELATIVE'. valid values are {valid_values}.")
        if self.set_odometer is None and self.set_maintenance is None and isinstance(self.relative, str):
            raise self._gcode.error("'RELATIVE' can only be used with 'SET_ODOMETER' or 'SET_MAINTENANCE'.")


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
        self._position = {"x": 0, "y": 0, "z": 0}

        self._db_fname = self._printer.get_start_args().get("config_file", "")
        self._db_fname = os.path.split(self._db_fname)[0]
        self._db_fname = os.path.dirname(self._db_fname)  # go back 1 folder level
        self._db_fname = os.path.join(self._db_fname, "database")
        os.makedirs(os.path.join(self._db_fname), exist_ok=True)
        self._db_fname = os.path.join(self._db_fname, _DB_NAME)

        dbm._defaultmod = dbm.dumb
        dbm._modules["dbm.dumb"] = dbm.dumb
        self._db = shelve.open(self._db_fname)
        dbm._defaultmod = None
        dbm._modules = {}

        self._lock = Lock()
        self._update_db = False
        self._ignore_position = False

        self._odometer = self._db.get("odometer", {"x": 0, "y": 0, "z": 0})

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

    def __del__(self):
        self._db.close()

    def _home_begin(self, *args, **kwargs) -> None:  # pylint: disable=unused-argument
        """
        This is called when the toolhead starts homing and sets a flag to ignore the
            position in our decorator.

        :param args: Keep compatibility with the event handler.
        :param kwargs: Keep compatibility with the event handler.
        :return:
        """
        self._ignore_position = True

    def _home_end(self, *args, **kwargs) -> None:  # pylint: disable=unused-argument
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
            if self._update_db:
                with self._lock:
                    self._db["odometer"] = self._odometer  # write the odometer to disk
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
        args = _Args(gcmd, self._gcode)

        if args.set_odometer is None and args.set_maintenance is None:
            self._return_odometer(args.unit)
        elif args.set_odometer is not None:
            unit = args.unit if args.unit is not None else "km"
            self._set_odometer(args.set_odometer, args.axes, unit, args.relative)
        elif args.set_maintenance is not None:
            unit = args.unit if args.unit is not None else "km"
            self._set_maintenance(args.set_maintenance, args.axes, unit, args.relative)

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
        with self._lock:
            next_maintenance = self._db.get(f"next_maintenance", {"x": None, "y": None, "z": None})
        for axis in self._odometer:
            raw_value = self._odometer[axis]
            unit = self._get_recommended_unit(raw_value)
            value = self._convert_mm_to_unit(raw_value, unit)
            result += f"{axis.upper()}: {value:.3f} {unit}\n"

            next_maintenance_axis = next_maintenance[axis]
            if next_maintenance_axis is not None:
                unit = self._get_recommended_unit(next_maintenance_axis - raw_value)
                next_maintenance_axis = self._convert_mm_to_unit(
                    next_maintenance_axis - raw_value, unit
                )
                if next_maintenance_axis > raw_value:
                    result += f"  Next maintenance in: {next_maintenance_axis:.3f} {unit}\n"
                else:
                    result += (
                        f"  Maintenance due: {next_maintenance_axis:.3f} {unit}\n"
                    )
            else:
                result += "  Maintenance not set.\n"
        self._gcode.respond_info(result)

    def _set_odometer(self, value: Union[int, float], axes: str, unit: str, relative: bool) -> None:
        """
        Set the odometer values.

        :param value: The value in the desired unit. It can be 'mm', 'm' or 'km'.
        :param axes: The axes to set. It can be 'x', 'y', 'z' or any combination of them.
        :param unit: The desired unit. It can be 'mm', 'm' or 'km'.
        :param relative: If True the value is added to the current odometer value.
        :return:
        """
        value = self._convert_unit_to_mm(value, unit)
        with self._lock:
            for axis in axes.lower():
                if axis not in "xyz":
                    raise self._gcode.error(f"Invalid '{axis}' axis.")
                add_value = self._odometer[axis] if relative else 0
                self._odometer[axis] = value + add_value
            self._db["odometer"] = self._odometer
        self._return_odometer()

    def _set_maintenance(self, value: Union[int, float], axes: str, unit: str, relative: bool) -> None:
        """
        Set the maintenance values.

        :param value: The value in the desired unit. It can be 'mm', 'm' or 'km'.
        :param axes: The axes to set. It can be 'x', 'y', 'z' or any combination of them.
        :param unit: The desired unit. It can be 'mm', 'm' or 'km'.
        :param relative: If True the value is added to the current maintenance value.
        :return:
        """
        value = self._convert_unit_to_mm(value, unit)
        with self._lock:
            next_maintenance = self._db.get(f"next_maintenance", {"x": None, "y": None, "z": None})
            maintenance_period = self._db.get(f"maintenance_period", {"x": None, "y": None, "z": None})
            for axis in axes.lower():
                if axis not in "xyz":
                    raise self._gcode.error(f"Invalid '{axis}' axis.")
                add_value = self._odometer[axis] if relative else 0
                next_maintenance[axis] = value + add_value
                maintenance_period[axis] = value
            self._db[f"next_maintenance"] = next_maintenance
            self._db[f"maintenance"] = maintenance_period


def load_config(config):
    """
    klippy calls this function to load the plugin.

    :param config:
    :return:
    """
    return MotionMinder(config)
