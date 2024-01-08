import sys

import requests

_MOONRAKER_URL = "http://127.0.0.1:7125"
_NAMESPACE = "motion_minder"


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


def set_odometer(moonraker_url, namespace, x=None, y=None, z=None):
    base_url = f"{moonraker_url}/server/database/item?namespace={namespace}"

    def update_axis(axis, value):
        if value is not None:
            requests.post(f"{base_url}&key=odometer_{axis}&value={value}")

    update_axis('x', x)
    update_axis('y', y)
    update_axis('z', z)


def get_odometer(moonraker_url, namespace):
    def get_odometer_value(key):
        response = requests.get(f"{base_url}&key={key}").json()
        if "error" in response:
            return 0
        else:
            return float(response.get("result", {}).get("value", 0))

    base_url = f"{moonraker_url}/server/database/item?namespace={namespace}"

    x = get_odometer_value("odometer_x")
    y = get_odometer_value("odometer_y")
    z = get_odometer_value("odometer_z")

    return x, y, z


def _update_odometer(x=None, y=None, z=None):
    base_url = f"{_MOONRAKER_URL}/server/database/item?namespace={_NAMESPACE}"

    def update_axis(axis, value):
        if value is not None:
            ret = requests.get(f"{base_url}&key=odometer_{axis}")
            curr_value = float(ret.json()["result"]["value"])
            new_value = value + curr_value
            requests.post(f"{base_url}&key=odometer_{axis}&value={new_value}")

    update_axis('x', x)
    update_axis('y', y)
    update_axis('z', z)


def _process_gcode(filename):
    x, y, z = _read_gcode(filename)
    _update_odometer(x, y, z)
    _query_db()


def _process_history(gcode_folder):
    n_jobs = requests.get(f"{_MOONRAKER_URL}/server/history/list?limit=1").json()["result"]["count"]
    jobs = requests.get(f"{_MOONRAKER_URL}/server/history/list?limit={n_jobs}").json()["result"]["jobs"]

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

    _update_odometer(total_x, total_y, total_z)
    _query_db()


def _reset_db(initial_km):
    base_url = f"{_MOONRAKER_URL}/server/database/item?namespace={_NAMESPACE}"

    # Reset init_value
    init_value_url = f"{base_url}&key=init_value&value={initial_km * 1000 * 1000}"
    requests.post(init_value_url)

    print(f"Database reset to: {initial_km} km")


def _query_db():
    base_url = f"{_MOONRAKER_URL}/server/database/item?namespace={_NAMESPACE}"

    def get_and_convert_value(key):
        url = f"{base_url}&key={key}"
        ret = requests.get(url)
        value = float(ret.json()["result"]["value"])
        return value / 1000 / 1000

    try:
        init_value = get_and_convert_value("init_value")
        curr_value_x = get_and_convert_value("odometer_x")
        curr_value_y = get_and_convert_value("odometer_y")
        curr_value_z = get_and_convert_value("odometer_z")
    except:
        print("Database not initialized. Please run `MOTION_MINDER INIT_KM=<initial_km>`")
        return

    health_x = (init_value - curr_value_x) / init_value
    health_y = (init_value - curr_value_y) / init_value
    health_z = (init_value - curr_value_z) / init_value

    print(f"Health of X axis: {health_x:.2%} (your X axis has traveled {curr_value_x:.3f} km)")
    print(f"Health of Y axis: {health_y:.2%} (your Y axis has traveled {curr_value_y:.3f} km)")
    print(f"Health of Z axis: {health_z:.2%} (your Z axis has traveled {curr_value_z:.3f} km)")


if __name__ == "__main__":

    arg = sys.argv[1].lower()
    if arg == "init_km":
        initial_km_ = float(sys.argv[2])
        _reset_db(initial_km_)
    elif arg == "reset":
        axis = sys.argv[2].lower()
        if axis not in ["x", "y", "z"]:
            raise ValueError("Axis must be X, Y or Z")
        set_odometer(_MOONRAKER_URL, _NAMESPACE, **{axis: 0})
        print(f"Odometer for axis {axis} reset to 0")
    elif arg == "query":
        _query_db()
    elif arg == "process_history":
        ret = requests.get(f"{_MOONRAKER_URL}/server/files/roots")
        folders = ret.json()["result"]
        gcode_folder_ = [folder for folder in folders if folder["name"] == "gcodes"][0]["path"]
        _process_history(gcode_folder_)
