import json
import random
import time
from threading import Thread

import requests
import websocket

import motion_minder

_MOONRAKER_URL = "192.168.100.96:7125"
_NAMESPACE = "motion_minder"


class PrinterOdometer:
    """
    This class is responsible for calculating the printer's odometer.
    """

    def __init__(self, update_interval: int = 20) -> None:
        """

        :param update_interval: The interval in messages between each odometer update.
        """
        self._id = random.randint(0, 10000)

        x, y, z = motion_minder.get_odometer(f"http://{_MOONRAKER_URL}", _NAMESPACE)
        self._odom = {"x": x, "y": y, "z": z}
        self._last_position = {"x": None, "y": None, "z": None}

        self._homed_axis = ""
        self._get_homed_axis()

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

    def _get_homed_axis(self) -> None:
        """
        Get the homed axis from the printer.

        :return:
        """
        ret = requests.get(f"http://{_MOONRAKER_URL}/printer/objects/query?toolhead")
        self._homed_axis = ""
        try:
            if 200 <= ret.status_code < 300:
                self._homed_axis = ret.json().get("result", {}).get("status", {}). \
                    get("toolhead", {}).get("homed_axes", "")
        except:
            pass

    def check_klipper_state_routine(self) -> None:
        """
        Check the klipper state and subscribe to the websocket when it's ready.
        Always when the Klipper is offline all the websocket subscriptions are lost.

        :return:
        """
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

    def _update_single_axis_odometer(self, axis: str, value: float) -> None:
        """
        Update the odometer for a single axis.

        :param axis: The axis to update.
        :param value: The current position of the axis, it will calculate the difference between the last position and
            the current position and add it to the odometer.
        :return:
        """
        if self._last_position[axis] is not None:
            self._odom[axis] += abs(value - self._last_position[axis])
        self._last_position[axis] = value

    def _process_motion_report(self, param: dict) -> None:
        """
        Process the motion report and update the odometer.

        :param param: The message received from the websocket that can contain the motion report or not.
        :return:
        """
        if "motion_report" not in param:
            return

        live_position = param["motion_report"].get("live_position", None)
        if live_position is None:
            return
        for i, axis in enumerate(["x", "y", "z"]):
            value = live_position[i]
            if value is not None and axis in self._homed_axis:
                self._update_single_axis_odometer(axis, value)
        self._messages_counter += 1

        if self._messages_counter % self._update_interval == 0:
            motion_minder.set_odometer(
                f"http://{_MOONRAKER_URL}", _NAMESPACE,
                self._odom["x"], self._odom["y"], self._odom["z"]
            )

    def _process_toolhead(self, param):
        """
        Process the toolhead message and get the homed axes.

        :param param: The message received from the websocket that can contain the toolhead message or not.
        :return:
        """
        if not "toolhead" in param:
            return
        homed_axes = param["toolhead"].get("homed_axes", None)
        if homed_axes is not None:
            self._homed_axis = homed_axes

    def _process_klipper_state(self, param):
        """
        Process the klipper state and subscribe to the websocket when it's ready.

        :param param: The message received from the websocket that can contain the klipper state or not.
        :return:
        """
        if not "klipper" in param:
            return
        klipper = param["klipper"]
        state = klipper.get("active_state", None)
        if state is not None and state == "inactive":
            self._subscribed = False

    def on_message(self, ws, message) -> None:
        """
        Process the message received from the websocket.

        :param ws: The websocket object.
        :param message: The message received from the websocket.
        :return:
        """
        message = json.loads(message)
        params = message["params"]
        for param in params:
            self._process_motion_report(param)
            self._process_toolhead(param)
            self._process_klipper_state(param)

    def subscribe(self, websock):
        """
        Subscribe to a specific topic from moonraker.

        :param websock: The websocket object.
        :return:
        """
        subscribe_objects = {
            "motion_report": None,
            "toolhead": ["homed_axes"],
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
        """
        Subscribe to the websocket when it's open.

        :param ws: The websocket object.
        :return:
        """
        self.subscribe(ws)


if __name__ == "__main__":
    p = PrinterOdometer()
