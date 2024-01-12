import json
import logging
import os
import random
import sys
import time
from logging import handlers
from threading import Thread

import requests
import websocket

MOONRAKER_ADDRESS = "127.0.0.1:7125"
NAMESPACE = "motion_minder"


class MoonrakerInterface:
    def __init__(self, moonraker_address, namespace,
                 connect_websocket=False, subscribe_objects=None, ws_callbacks=None):
        self._moonraker_address = moonraker_address
        self._namespace = namespace
        self._connect_websocket = connect_websocket

        self._id = random.randint(0, 10000)
        self._subscribe_objects = {} if subscribe_objects is None else subscribe_objects
        self._on_message_ws_callbacks = [] if ws_callbacks is None else ws_callbacks
        self._subscribed = False

        if self._connect_websocket:
            self._websocket = None
            self._connect_to_websocket()

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

    def get_roots(self):
        endpoint = f"http://{self._moonraker_address}/server/files/roots"
        response = requests.get(f"{endpoint}").json()
        if "error" in response:
            return {}
        else:
            folders_list = response.get("result", [])
            folders = {}
            for folder in folders_list:
                folders[folder["name"]] = folder
                folders[folder["name"]].pop("name")
            return folders

    def get_obj(self, obj: str) -> dict:
        """
        Get the homed axis from the printer.

        :return:
        """
        ret = requests.get(f"http://{self._moonraker_address}/printer/objects/query?toolhead")
        try:
            if 200 <= ret.status_code < 300:
                return ret.json().get("result", {}).get("status", {}).get(obj, {})
            else:
                logging.error(f"Error getting the homed axis: {ret.status_code}")
        except Exception as e:
            logging.error(f"Error getting the homed axis: {e}", exc_info=True)
        return {}

    def get_jobs_history(self, limit=None):
        if limit is None:
            limit = requests.get(f"{self._moonraker_address}/server/history/list?limit=1").json()["result"]["count"]
        jobs = requests.get(f"{self._moonraker_address}/server/history/list?limit={limit}").json()["result"]["jobs"]
        return jobs

    def _check_klipper_state_routine(self) -> None:
        """
        Check the klipper state and subscribe to the websocket when it's ready.
        Always when the Klipper is offline all the websocket subscriptions are lost.

        :return:
        """
        while True:
            if not self._subscribed:
                try:
                    klipper_state = requests.get(f"http://{self._moonraker_address}/server/info")
                    if 200 <= klipper_state.status_code < 300:
                        klipper_state = klipper_state.json()["result"]["klippy_state"]
                        if klipper_state == "ready":
                            self._subscribe(self._subscribe_objects)
                            self._subscribed = True
                    else:
                        logging.error(f"Error checking the klipper state: {klipper_state.status_code}")
                except Exception as e:
                    logging.error(f"Error checking the klipper state: {e}", exc_info=True)
            time.sleep(2)

    def _connect_to_websocket(self):
        self._websocket = websocket.WebSocketApp(
            f"ws://{self._moonraker_address}/websocket",
            on_message=self._ws_on_message,
            on_open=self._ws_on_open,
        )
        thread = Thread(target=self._websocket.run_forever, kwargs={"reconnect": True})
        thread.daemon = True
        thread.start()
        # self.websocket.run_forever(reconnect=5)

        state_thread = Thread(target=self._check_klipper_state_routine)
        state_thread.daemon = True
        state_thread.start()

    def _subscribe(self, subscribe_objects):

        self._websocket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "printer.objects.subscribe",
                    "params": {"objects": subscribe_objects},
                    "id": self._id,
                }
            )
        )

    def _process_klipper_state(self, param):
        """
        Process the klipper state and subscribe to the websocket when it's ready.

        :param param: The message received from the websocket that can contain the klipper state or not.
        :return:
        """
        if not "method" in param:
            return
        state = param.get("method", None)
        if state is not None and state == "notify_klippy_disconnected":
            self._subscribed = False

    def _ws_on_message(self, _, message):
        message = json.loads(message)
        for callback in self._on_message_ws_callbacks:
            try:
                callback(message)
            except Exception as e:
                logging.error(f"Error in the callback: {e}", exc_info=True)
        self._process_klipper_state(message)

    def _ws_on_open(self, ws):
        if len(self._subscribe_objects) > 0:
            self._subscribe(self._subscribe_objects)


class MotionMinder(MoonrakerInterface):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._logger = logging.getLogger("motion_minder")
        self._setup_logger()

    def _setup_logger(self):
        self._logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(formatter)
        self._logger.addHandler(sh)

        logs_folder = self.get_roots().get("logs", {}).get("path", None)
        if logs_folder is not None:
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            rh = logging.handlers.RotatingFileHandler(os.path.join(logs_folder, 'motion_minder.log'),
                                                      maxBytes=5 * 1024 * 1024, backupCount=5)
            rh.setLevel(logging.DEBUG)
            rh.setFormatter(formatter)
            self._logger.addHandler(rh)

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
        current_odometer = {}
        for axis_value, name in zip([x, y, z], ["x", "y", "z"]):
            if axis_value is not None:
                value = self.get_key_value(f"odometer_{name}")
                if value is not None:
                    axis_value += float(value)
                self.set_key_value(f"odometer_{name}", axis_value)
                current_odometer[f"odometer_{name}"] = axis_value
        return current_odometer

    @property
    def logger(self):
        return self._logger


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
    jobs = mm.get_jobs_history()
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

    mm.logger.info(f"Database reset to: {initial_km} km")

    x, y, z = mm.get_odometer()

    for axis, value in zip(["x", "y", "z"], [x, y, z]):
        mm.set_key_value(f"odometer_on_reset_{axis}", value)


def _query_db(mm):
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
        mm.logger.error("Database not initialized. Please run `MOTION_MINDER INIT_KM=<initial_km>`")
        return

    health_x = (init_value - (curr_value_x - value_on_reset_x)) / init_value
    health_y = (init_value - (curr_value_y - value_on_reset_y)) / init_value
    health_z = (init_value - (curr_value_z - value_on_reset_z)) / init_value

    mm.logger.info(f"Health of X axis: {health_x:.2%} (your X axis has traveled {curr_value_x:.3f} km)")
    mm.logger.info(f"Health of Y axis: {health_y:.2%} (your Y axis has traveled {curr_value_y:.3f} km)")
    mm.logger.info(f"Health of Z axis: {health_z:.2%} (your Z axis has traveled {curr_value_z:.3f} km)")


def main():
    arg = sys.argv[1].lower()
    mm = MotionMinder(moonraker_address=MOONRAKER_ADDRESS, namespace=NAMESPACE)
    if arg == "init_km":
        initial_km_ = float(sys.argv[2])
        _reset_db(initial_km_, mm)
    elif arg == "reset":
        axis = sys.argv[2].lower()
        if axis not in ["x", "y", "z"]:
            raise ValueError("Axis must be X, Y or Z")
        mm.set_odometer(**{axis: 0})
        mm.logger.info(f"Odometer for axis {axis} reset to 0")
    elif arg == "query":
        _query_db(mm)
    elif arg == "process_history":
        gcode_folder_ = mm.get_roots().get("gcodes", None)
        if gcode_folder_ is None:
            mm.logger.error("Gcode folder not set. Please set it in your moonraker config")
            exit(-1)
        _process_history(gcode_folder_, mm)


if __name__ == "__main__":
    main()
