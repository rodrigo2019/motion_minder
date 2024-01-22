import os
import shelve
import time
from threading import Thread

_db_name = "motion_minder.dbm"


class MotionMinder:
    def __init__(self, config):
        self._config = config
        self._printer = config.get_printer()
        self._toolhead = None
        self._gcode = self._printer.lookup_object('gcode')
        self._steppers = {"x": None, "y": None, "z": None}
        self._position = {"x": 0, "y": 0, "z": 0}

        self._db_fname = os.path.split(self._printer.get_start_args().get("config_file", ""))[0]
        self._db_fname = os.path.dirname(self._db_fname)  # go back 1 folder level
        self._db_fname = os.path.join(self._db_fname, "database", _db_name)

        with shelve.open(self._db_fname) as db:
            self._odometer = db.get("odometer", {"x": 0, "y": 0, "z": 0})

        self._printer.register_event_handler("klippy:mcu_identify", self._get_toolhead)

        self._thread = Thread(target=self._motion_minder_thread)
        self._thread.daemon = True
        self._thread.start()

        self._gcode.register_command("MOTION_MINDER", self._cmd_motion_minder, desc="Get/set odometer values.")

    def _motion_minder_thread(self):
        while True:
            time.sleep(5)
            with shelve.open(self._db_fname) as db:
                db["odometer"] = self._odometer

    def _get_toolhead(self):
        self._toolhead = self._printer.lookup_object('toolhead')
        kinematics = self._toolhead.get_kinematics()
        steppers = kinematics.get_steppers()

        for stepper in steppers:
            stepper_name = stepper.get_name()
            stepper_axis = stepper_name.split("_")[1]
            if stepper_axis in self._steppers:
                self._steppers[stepper_axis] = stepper
                self._position[stepper_axis] = stepper.get_mcu_position() * stepper.get_step_dist()
                self._steppers[stepper_axis].add_active_callback(self._configure_callback(stepper_axis))

    def _configure_callback(self, axis):

        def callback(_):
            current_position = self._steppers[axis].get_mcu_position()
            current_position *= self._steppers[axis].get_step_dist()
            delta = abs(current_position - self._position[axis])
            self._position[axis] = current_position
            self._odometer[axis] += delta
            self._steppers[axis].add_active_callback(self._configure_callback(axis))

        return callback

    def _cmd_motion_minder(self, gcmd):
        set_value = gcmd.get_float("SET", None)
        set_maintenance = gcmd.get_float("SET_MAINTENANCE", None)
        axes = gcmd.get("AXES", "xyz")
        unit = gcmd.get("UNIT", "km")

        if set_value is None and set_maintenance is None:
            self._return_odometer()
        elif set_value is not None:
            self._set_odometer(set_value, axes, unit)
        elif set_maintenance is not None:
            self._set_maintenance(set_maintenance, axes, unit)

    @staticmethod
    def _get_recommended_unit(value):
        if value < 1000:
            return "mm"
        elif value < 1000000:
            return "m"
        return "km"

    @staticmethod
    def _convert_mm_to_unit(value, unit):
        if unit == "m":
            return value / 1000
        elif unit == "km":
            return value / 1000000
        return value

    def _return_odometer(self):
        result = ""
        for axis in self._odometer:
            raw_value = self._odometer[axis]
            unit = self._get_recommended_unit(raw_value)
            value = self._convert_mm_to_unit(raw_value, unit)
            result += f"{axis.upper()}: {value:.3f} {unit}\n"
            with shelve.open(self._db_fname) as db:
                next_maintenance = db.get(f"next_maintenance_{axis}", None)
                if next_maintenance is not None and next_maintenance > value:
                    unit = self._get_recommended_unit(next_maintenance - raw_value)
                    next_maintenance = self._convert_mm_to_unit(next_maintenance - raw_value, unit)
                    result += f"  Next maintenance in: {next_maintenance:.3f} {unit}\n"
                elif next_maintenance is not None:
                    unit = self._get_recommended_unit(raw_value - next_maintenance)
                    next_maintenance = self._convert_mm_to_unit(raw_value - next_maintenance, unit)
                    result += f"  Maintenance due: {next_maintenance:.3f} {unit}\n"
                else:
                    result += f"  Maintenance not set.\n"
        self._gcode.respond_info(result)

    def _set_odometer(self, value, axes, unit):
        if unit not in ["mm", "m", "km"]:
            raise self._gcode.error(f"Invalid unit '{unit}'.")

        if unit == "m":
            value *= 1_000
        elif unit == "km":
            value *= 1_000_000
        for axis in axes.lower():
            if axis not in "xyz":
                raise self._gcode.error(f"Invalid '{axis}' axis.")
            self._odometer[axis] = value
        self._return_odometer()

    def _set_maintenance(self, value, axes, unit):
        if unit not in ["mm", "m", "km"]:
            raise self._gcode.error(f"Invalid unit '{unit}'.")

        if unit == "m":
            value *= 1_000
        elif unit == "km":
            value *= 1_000_000
        for axis in axes.lower():
            if axis not in "xyz":
                raise self._gcode.error(f"Invalid '{axis}' axis.")
            with shelve.open(self._db_fname) as db:
                db[f"next_maintenance_{axis}"] = value + self._odometer[axis]
                db[f"maintenance_{axis}"] = value


def load_config(config):
    return MotionMinder(config)
