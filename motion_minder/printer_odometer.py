import websocket
import requests
import random
import json
import motion_minder
import time
from threading import Thread

_MOONRAKER_URL = "127.0.0.1:7125"
_NAMESPACE = "motion_minder"


class PrinterOdometer:
    def __init__(self, update_interval=20):
        self._id = random.randint(0, 10000)

        x, y, z = motion_minder.get_odometer(f"http://{_MOONRAKER_URL}", _NAMESPACE)
        self._odom = {"x": x, "y": y, "z": z}
        self._last_position = {"x": None, "y": None, "z": None}
        self._messages_counter = 0
        self._update_interval = update_interval
        self._subscribed = False

        self._state_thread = Thread(target=self.check_klipper_state_routine)
        self._state_thread.daemon = True
        self._state_thread.start()

        self.websocket = websocket.WebSocketApp(
            f"ws://{_MOONRAKER_URL}/websocket",
            on_message=self.on_message,
            on_open=self.on_open,
        )
        self.websocket.run_forever(reconnect=5)

    def check_klipper_state_routine(self):
        while True:
            if not self._subscribed:
                try:
                    klipper_state = requests.get(f"http://{_MOONRAKER_URL}/server/info")
                    if 200 <= klipper_state.status_code < 300:
                        klipper_state = klipper_state.json()["result"]["klippy_state"]
                        if klipper_state == "ready":
                            self.subscribe(self.websocket)
                            self._subscribed = True
                except:
                    pass
            time.sleep(2)

    def on_message(self, ws, message):
        message = json.loads(message)
        params = message["params"]
        for param in params:
            if "motion_report" in param:
                live_position = param["motion_report"].get("live_position", None)
                if live_position is not None:
                    x, y, z, _ = live_position
                    if x is not None:
                        if self._last_position["x"] is not None:
                            self._odom["x"] += abs(x - self._last_position["x"])
                        self._last_position["x"] = x
                    if y is not None:
                        if self._last_position["y"] is not None:
                            self._odom["y"] += abs(y - self._last_position["y"])
                        self._last_position["y"] = y
                    if z is not None:
                        if self._last_position["z"] is not None:
                            self._odom["z"] += abs(z - self._last_position["z"])
                        self._last_position["z"] = z

                self._messages_counter += 1
                if self._messages_counter % self._update_interval == 0:
                    motion_minder.set_odometer(
                        f"http://{_MOONRAKER_URL}", _NAMESPACE,
                        self._odom["x"], self._odom["y"], self._odom["z"]
                    )
            elif "klipper" in param:
                klipper = param["klipper"]
                state = klipper.get("active_state", None)
                if state is not None and state == "inactive":
                    self._subscribed = False

    def subscribe(self, websock):
        subscribe_objects = {
            "motion_report": None
        }

        websock.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "printer.objects.subscribe",
                    "params": {"objects": subscribe_objects},
                    "id": self._id,
                }
            )
        )

    def on_open(self, ws):
        self.subscribe(ws)


if __name__ == "__main__":
    p = PrinterOdometer()
