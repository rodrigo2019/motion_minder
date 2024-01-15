import argparse
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

parser = argparse.ArgumentParser(description="Motion Minder")
parser.add_argument("--next-maintenance", type=int, help="Next maintenance in kilometers")
parser.add_argument("--set-axis", type=int, help="Reset odometer for axis.")
parser.add_argument("--stats", action="store_true", help="Motion Minder stats.")
parser.add_argument("--process-history", action="store_true", help="Process printer history.")
parser.add_argument("--axis", type=str, help="Axis to reset.", default="xyz")

MOONRAKER_ADDRESS = "127.0.0.1:7125"
NAMESPACE = "motion_minder"

_logger = logging.getLogger("motion_minder")
_logger.setLevel(logging.DEBUG)
_formatter = logging.Formatter("[%(levelname)s] %(message)s")
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.DEBUG)
_sh.setFormatter(_formatter)
_logger.addHandler(_sh)


class MoonrakerInterface:
    def __init__(
            self,
            moonraker_address,
            namespace,
            connect_websocket=False,
            subscribe_objects=None,
            ws_callbacks=None,
    ):
        self._moonraker_address = moonraker_address
        self._namespace = namespace
        self._connect_websocket = connect_websocket

        self._id = random.randint(0, 10000)
        self._subscribe_objects = {} if subscribe_objects is None else subscribe_objects
        self._on_message_ws_callbacks = [] if ws_callbacks is None else ws_callbacks
        self._subscribed = False

        self._setup_logger()
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
        ret = requests.get(
            f"http://{self._moonraker_address}/printer/objects/query?{obj}"
        )
        try:
            if 200 <= ret.status_code < 300:
                return ret.json().get("result", {}).get("status", {}).get(obj, {})
            else:
                _logger.error(
                    f"Error getting the homed axis. GET status code:{ret.status_code}"
                )
        except Exception as e:
            _logger.error(f"Error getting the homed axis: {e}", exc_info=True)
        return {}

    def get_jobs_history(self, limit=None):
        if limit is None:
            limit = requests.get(
                f"http://{self._moonraker_address}/server/history/list?limit=1"
            ).json()["result"]["count"]
        jobs = requests.get(
            f"http://{self._moonraker_address}/server/history/list?limit={limit}"
        ).json()["result"]["jobs"]
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
                    klipper_state = requests.get(
                        f"http://{self._moonraker_address}/server/info"
                    )
                    if 200 <= klipper_state.status_code < 300:
                        klipper_state = klipper_state.json()["result"]["klippy_state"]
                        if klipper_state == "ready":
                            self._subscribe(self._subscribe_objects)
                            self._subscribed = True
                    else:
                        _logger.error(
                            f"Error checking the klipper state.  GET status code {klipper_state.status_code}"
                        )
                except Exception as e:
                    _logger.error(
                        f"Error checking the klipper state: {e}", exc_info=True
                    )
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
        if "method" not in param:
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

    def _setup_logger(self, keep_trying=False):
        while True:
            logs_folder = self.get_roots().get("logs", {}).get("path", None)
            if logs_folder is None and not keep_trying:
                _logger.warning(
                    "Logs folder not found. Starting a thread to keep trying."
                )
                thread = Thread(target=self._setup_logger, kwargs={"keep_trying": True})
                thread.daemon = True
                thread.start()
                break
            if logs_folder is None and keep_trying:
                time.sleep(2)
                continue
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            rh = logging.handlers.RotatingFileHandler(
                os.path.join(logs_folder, "motion_minder.log"),
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
            )
            rh.setLevel(logging.DEBUG)
            rh.setFormatter(formatter)
            _logger.addHandler(rh)
            break


class MotionMinder(MoonrakerInterface):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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


class GCodeReader:
    _VALID_COMMANDS = {"G90", "G91", "G92", "G1", "G0", "M82", "M83"}

    def __init__(self, file_path):
        self._file_path = file_path
        self._file = open(file_path, "r")

        self._mode = "absolute"
        self._extruder_mode = "absolute"

        self._last_positions = {"x": 0.0, "y": 0.0, "z": 0.0, "e": 0.0}
        self._total_distances = {"x": 0.0, "y": 0.0, "z": 0.0, "e": 0.0}

    def read(self, file_position=None, max_extrusion=None):
        distances = self._total_distances.copy()

        while True:
            if file_position is not None and self._file.tell() >= file_position:
                break
            line = self._file.readline()
            if not line:
                break
            command, *values = line.split(" ")
            if command not in GCodeReader._VALID_COMMANDS:
                continue
            moves = {}
            for value in values:
                try:
                    moves[value[0]] = float(value[1:])
                except ValueError:
                    pass

            if command == "G90":
                self._mode = "absolute"
                self._extruder_mode = "absolute"
            elif command == "G91":
                self._mode = "relative"
                self._extruder_mode = "relative"
            elif command == "M82":
                self._extruder_mode = "absolute"
            elif command == "M83":
                self._extruder_mode = "relative"
            elif command in ["G1", "G0"]:
                for axis in ["X", "Y", "Z"]:
                    if axis in moves:
                        current_value = moves[axis]
                        self._total_distances[axis.lower()] += (
                            abs(current_value - self._last_positions[axis.lower()])
                            if self._mode == "absolute"
                            else current_value
                        )
                        self._last_positions[axis.lower()] = current_value
                if "E" in moves:
                    self._total_distances["e"] = (
                        abs(moves["E"] - self._last_positions["e"])
                        if self._extruder_mode == "absolute"
                        else moves["E"]
                    )
                    self._last_positions["e"] = moves["E"]
            elif command == "G92":
                for axis in ["X", "Y", "Z", "E"]:
                    if axis in moves:
                        self._last_positions[axis.lower()] = moves[axis]

            if max_extrusion is not None and distances["e"] > max_extrusion:
                break
        for axis in ["x", "y", "z", "e"]:
            distances[axis] = self._total_distances[axis] - distances[axis]

        return distances

    def close(self):
        self._file.close()


def _process_history(gcode_folder, mm):
    jobs = mm.get_jobs_history()
    total_x = 0
    total_y = 0
    total_z = 0
    for job in jobs:
        if not job["exists"]:
            continue
        if job["status"] != "complete":
            max_extrusion = job["filament_used"]
        else:
            max_extrusion = None
        fname = f"{gcode_folder}/{job['filename']}"
        x, y, z, _ = GCodeReader(fname).read(max_extrusion=max_extrusion).values()
        total_x += x
        total_y += y
        total_z += z

    mm.add_mileage(x=total_x, y=total_y, z=total_z)
    _query_db(mm)


def _set_next_maintenance(mm, x=None, y=None, z=None):

    odo_x, odo_y, odo_z = mm.get_odometer()

    for axis, value, nm in zip(["x", "y", "z"], [odo_x, odo_y, odo_z], [x, y, z]):
        if nm is None:
            continue
        nm = mm.set_key_value(f"next_maintenance_{axis}", nm * 1e6)
        mm.set_key_value(f"odometer_on_reset_{axis}", value)
        _logger.info(f"{axis.upper()} maintenance at {(value + float(nm))/1e6:.3f} km.")


def _query_db(mm):
    def get_and_convert_value(key):
        value = float(mm.get_key_value(key))
        return value / 1e6

    try:
        for axis in ["x", "y", "z"]:
            next_maintenance = get_and_convert_value(f"next_maintenance_{axis}")
            value_on_reset = get_and_convert_value(f"odometer_on_reset_{axis}")
            curr_value = get_and_convert_value(f"odometer_{axis}")

            health = (next_maintenance - (curr_value - value_on_reset)) / next_maintenance
            _logger.info(
                f"Health of {axis.upper()} axis: {health:.2%} (your {axis} axis has traveled {curr_value:.3f} km)"
            )
    except Exception as e:
        _logger.error(f"Error while querying database: {e}", exc_info=True)
        _logger.error(
            "Did you set a maintenance for each axis? Please run `MOTION_MINDER NEXT_MAINTENANCE=<value>`"
        )
        return


def main(args):
    mm = MotionMinder(moonraker_address=MOONRAKER_ADDRESS, namespace=NAMESPACE)
    if args.next_maintenance is not None:
        kwargs = {}
        for axis in args.axis.lower():
            kwargs[axis] = args.next_maintenance
        _set_next_maintenance(mm=mm, **kwargs)
    elif args.set_axis is not None:
        for axis in args.axis.lower():
            if axis not in ["x", "y", "z"]:
                raise ValueError("Axis must be `X`, `Y`, `Z`  or any combination e.g: `XYZ`, `XZ`, `ZX`")
            mm.set_odometer(**{axis: args.set_axis})
            _logger.info(f"Odometer for axis {axis} reset to {args.set_axis} km")
    elif args.stats:
        _query_db(mm)
    elif args.process_history:
        gcode_folder_ = mm.get_roots().get("gcodes", None)
        if gcode_folder_ is None:
            _logger.error(
                "Gcode folder not set. Please set it in your moonraker config"
            )
            exit(-1)
        _process_history(gcode_folder_, mm)


if __name__ == "__main__":
    main(parser.parse_args())
