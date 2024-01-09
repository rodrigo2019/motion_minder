import sys

import requests

MOONRAKER_ADDRESS = "http://127.0.0.1:7125"
NAMESPACE = "motion_minder"


class MotionMinderMoonrakerDB:
    def __init__(self, moonraker_address, namespace):
        self._moonraker_address = moonraker_address
        self._namespace = namespace

    def get_key_value(self, key):
        base_url = f"http://{self._moonraker_address}/server/database/item?namespace={self._namespace}"
        response = requests.get(f"{base_url}&key={key}").json()
        if "error" in response:
            return None
        else:
            return response.get("result", {}).get("value", None)

    def set_key_value(self, key, value):
        base_url = f"http://{self._moonraker_address}/server/database/item?namespace={self._namespace}"
        response = requests.post(f"{base_url}&key={key}&value={value}").json()
        if "error" in response:
            return None
        else:
            return response.get("result", {}).get("value", None)

    def set_odometer(self, x=None, y=None, z=None):
        if x is not None:
            self.set_key_value("odometer_x", x)
        if y is not None:
            self.set_key_value("odometer_y", y)
        if z is not None:
            self.set_key_value("odometer_z", z)

    def get_odometer(self):
        x = self.get_key_value("odometer_x")
        y = self.get_key_value("odometer_y")
        z = self.get_key_value("odometer_z")
        return x, y, z

    def add_mileage(self, x=None, y=None, z=None):
        for axis, name in zip([x, y, z], ["x", "y", "z"]):
            if axis is not None:
                value = self.get_key_value(f"odometer_{name}")
                if value is not None:
                    axis += float(value)
                self.set_key_value(f"odometer_{name}", axis)


def _read_gcode(filename, max_extrusion=None):
    valid_commands = {"G90", "G91", "G92", "G1", "G0", "M82", "M83"}

    mode = "absolute"
    extruder_mode = "absolute"
    distances = {"x": 0, "y": 0, "z": 0, "e": 0}
    last_positions = {"x": 0, "y": 0, "z": 0, "e": 0}

    with open(filename) as f:
        for line in f:
            command, *values = line.split(" ")
            if command not in valid_commands:
                continue
            moves = {}
            for value in values:
                try:
                    moves[value[0]] = float(value[1:])
                except ValueError:
                    pass

            if command == "G90":
                mode = "absolute"
                extruder_mode = "absolute"
            elif command == "G91":
                mode = "relative"
                extruder_mode = "relative"
            elif command == "M82":
                extruder_mode = "absolute"
            elif command == "M83":
                extruder_mode = "relative"
            elif command in ["G1", "G0"]:
                for axis in ["X", "Y", "Z"]:
                    if axis in moves:
                        current_value = moves[axis]
                        distances[axis.lower()] += abs(
                            current_value - last_positions[axis.lower()]) \
                            if mode == "absolute" else current_value
                        last_positions[axis.lower()] = current_value
                if "E" in moves:
                    distances["e"] = abs(moves["E"] - last_positions["e"]) \
                        if extruder_mode == "absolute" else moves["E"]
                    last_positions["e"] = moves["E"]
            elif command == "G92":
                for axis in ["X", "Y", "Z", "E"]:
                    if axis in moves:
                        last_positions[axis.lower()] = moves[axis]

            if max_extrusion is not None and distances["e"] > max_extrusion:
                break

        return distances["x"], distances["y"], distances["z"]


def _process_history(gcode_folder, mm):
    n_jobs = requests.get(f"{MOONRAKER_ADDRESS}/server/history/list?limit=1").json()["result"]["count"]
    jobs = requests.get(f"{MOONRAKER_ADDRESS}/server/history/list?limit={n_jobs}").json()["result"]["jobs"]

    total_x = 0
    total_y = 0
    total_z = 0
    for job in jobs:
        if not job["exists"]:
            continue
        if job['status'] != 'complete':
            max_extrusion = job['filament_used']
        else:
            max_extrusion = None
        fname = f"{gcode_folder}/{job['filename']}"
        x, y, z = _read_gcode(fname, max_extrusion)
        total_x += x
        total_y += y
        total_z += z

    mm.add_mileage(x=total_x, y=total_y, z=total_z)
    _query_db(mm)


def _reset_db(initial_km, mm):
    mm.set_key_value("init_value", initial_km * 1000 * 1000)

    print(f"Database reset to: {initial_km} km")

    x, y, z = mm.get_odometer()

    for axis, value in zip(["x", "y", "z"], [x, y, z]):
        mm.set_key_value(f"odometer_on_reset_{axis}", value)


def _query_db(mm):
    base_url = f"{MOONRAKER_ADDRESS}/server/database/item?namespace={NAMESPACE}"

    def get_and_convert_value(key):
        value = float(mm.get_key_value(key))
        return value / 1000 / 1000

    try:
        init_value = get_and_convert_value("init_value")
        value_on_reset_x = get_and_convert_value("odometer_on_reset_x")
        value_on_reset_y = get_and_convert_value("odometer_on_reset_y")
        value_on_reset_z = get_and_convert_value("odometer_on_reset_z")
        curr_value_x = get_and_convert_value("odometer_x")
        curr_value_y = get_and_convert_value("odometer_y")
        curr_value_z = get_and_convert_value("odometer_z")
    except:
        print("Database not initialized. Please run `MOTION_MINDER INIT_KM=<initial_km>`")
        return

    health_x = (init_value - (curr_value_x - value_on_reset_x)) / init_value
    health_y = (init_value - (curr_value_y - value_on_reset_y)) / init_value
    health_z = (init_value - (curr_value_z - value_on_reset_z)) / init_value

    print(f"Health of X axis: {health_x:.2%} (your X axis has traveled {curr_value_x:.3f} km)")
    print(f"Health of Y axis: {health_y:.2%} (your Y axis has traveled {curr_value_y:.3f} km)")
    print(f"Health of Z axis: {health_z:.2%} (your Z axis has traveled {curr_value_z:.3f} km)")


def main():
    arg = sys.argv[1].lower()
    mm = MotionMinderMoonrakerDB(MOONRAKER_ADDRESS, NAMESPACE)
    if arg == "init_km":
        initial_km_ = float(sys.argv[2])
        _reset_db(initial_km_, mm)
    elif arg == "reset":
        axis = sys.argv[2].lower()
        if axis not in ["x", "y", "z"]:
            raise ValueError("Axis must be X, Y or Z")
        mm.set_odometer(**{axis: 0})
        print(f"Odometer for axis {axis} reset to 0")
    elif arg == "query":
        _query_db(mm)
    elif arg == "process_history":
        ret = requests.get(f"{MOONRAKER_ADDRESS}/server/files/roots")
        folders = ret.json()["result"]
        gcode_folder_ = [folder for folder in folders if folder["name"] == "gcodes"][0]["path"]
        _process_history(gcode_folder_, mm)


if __name__ == "__main__":
    main()
