import motion_minder
import time


class PrinterOdometer:
    """
    This class is responsible for calculating the printer's odometer.
    """

    def __init__(self, moonraker_address, update_interval: int = 20, **kwargs) -> None:
        """

        :param update_interval: The interval in messages between each odometer update.
        """
        self._moonraker_db = motion_minder.MotionMinder(moonraker_address=moonraker_address,
                                                        namespace=kwargs.get("namespace", "motion_minder"),
                                                        connect_websocket=True,
                                                        subscribe_objects={"motion_report": None,
                                                                           "toolhead": ["homed_axes"]},
                                                        ws_callbacks=[self.on_message]
                                                        )
        self._moonraker_address = moonraker_address

        self._diff_dist = {"x": 0, "y": 0, "z": 0}
        self._last_position = {"x": None, "y": None, "z": None}

        toolhead_stats = self._moonraker_db.get_obj("toolhead")
        self._homed_axis = toolhead_stats.get("homed_axes", "")
        self._axis_min = toolhead_stats.get("axis_minimum", [None, None, None])
        self._axis_max = toolhead_stats.get("axis_maximum", [None, None, None])

        self._messages_counter = 0
        self._update_interval = update_interval

    def _update_single_axis_odometer(self, axis: str, value: float) -> None:
        """
        Update the odometer for a single axis.

        :param axis: The axis to update.
        :param value: The current position of the axis, it will calculate the difference between the last position and
            the current position and add it to the odometer.
        :return:
        """
        if self._last_position[axis] is not None:
            self._diff_dist[axis] += abs(value - self._last_position[axis])
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
            self._moonraker_db.add_mileage(**self._diff_dist)
            self._diff_dist = {"x": 0, "y": 0, "z": 0}

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

    def on_message(self, message) -> None:
        """
        Process the message received from the websocket.

        :param ws: The websocket object.
        :param message: The message received from the websocket.
        :return:
        """
        params = message.get("params", [])
        for param in params:
            if not isinstance(param, dict):
                continue
            self._process_motion_report(param)
            self._process_toolhead(param)


if __name__ == "__main__":
    p = PrinterOdometer(moonraker_address=motion_minder.MOONRAKER_ADDRESS, namespace=motion_minder.NAMESPACE)
    while True:
        time.sleep(60)
