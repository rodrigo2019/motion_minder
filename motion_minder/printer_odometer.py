"""This file may be distributed under the terms of the GNU GPLv3 license"""
import time
import logging
import motion_minder

_logger = logging.getLogger("motion_minder").getChild("printer_odometer")


class PrinterOdometer:
    """
    This class is responsible for calculating the printer's odometer.
    """

    def __init__(
        self, moonraker_address: str, update_interval: int = 5, **kwargs
    ) -> None:
        """

        :param update_interval: The interval in messages between each odometer update.
        """
        self._diff_dist = {"x": 0, "y": 0, "z": 0}
        self._last_position = {"x": None, "y": None, "z": None}

        self._last_update = time.time()
        self._update_interval = update_interval

        self._printing_file = None

        self._motion_minder = motion_minder.MotionMinder(
            moonraker_address=moonraker_address,
            namespace=kwargs.get("namespace", "motion_minder"),
            connect_websocket=True,
            subscribe_objects={
                "motion_report": None,
                "toolhead": ["homed_axes"],
                "virtual_sdcard": None,
            },
            ws_callbacks=[self.on_message],
        )
        self._moonraker_address = moonraker_address

        toolhead_stats = self._motion_minder.get_obj("toolhead")
        self._homed_axes = toolhead_stats.get("homed_axes", "")
        self._axes_min = toolhead_stats.get("axis_minimum", [None, None, None])
        self._axes_max = toolhead_stats.get("axis_maximum", [None, None, None])

        _logger.info("Printer odometer initialized.")

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

    def _check_update_db_odometer(self, _: dict) -> None:
        """
        Check if the odometer needs to be updated and update it if necessary.

        :param _:
        :return:
        """
        if (
            time.time() - self._last_update > self._update_interval
            and any(self._diff_dist.values()) > 0
        ):
            current_odometer = self._motion_minder.add_mileage(**self._diff_dist)
            _logger.debug(
                f"Printer odometer updated. {self._diff_dist} // {current_odometer}"
            )
            self._diff_dist = {"x": 0, "y": 0, "z": 0}
            self._last_update = time.time()

    def _process_motion_report(self, param: dict) -> None:
        """
        Process the motion report and update the odometer.

        :param param: The message received from the websocket that can contain 
            the motion report or not.
        :return:
        """

        if "motion_report" not in param or self._printing_file is not None:
            return

        if any([x is None for x in self._axes_max + self._axes_min]):
            toolhead_stats = self._motion_minder.get_obj("toolhead")
            self._homed_axes = toolhead_stats.get("homed_axes", "")
            self._axes_min = toolhead_stats.get("axis_minimum", [None, None, None])
            self._axes_max = toolhead_stats.get("axis_maximum", [None, None, None])
            if any([x is None for x in self._axes_max + self._axes_min]):
                return

        live_position = param["motion_report"].get("live_position", None)

        if live_position is None:
            return
        for i, axis in enumerate(["x", "y", "z"]):
            value = live_position[i]
            if (
                axis in self._homed_axes
                and self._axes_min[i] <= value <= self._axes_max[i]
            ):
                self._update_single_axis_odometer(axis, value)

    def _process_toolhead(self, param: dict) -> None:
        """
        Process the toolhead message and get the homed axes.

        :param param: The message received from the websocket that can contain 
            the toolhead message or not.
        :return:
        """
        if "toolhead" not in param:
            return
        homed_axes = param["toolhead"].get("homed_axes", None)
        if homed_axes is not None:
            self._homed_axes = homed_axes

    def _process_virtual_sdcard(self, param: dict) -> None:
        """
        Process the virtual sdcard message and start reading the file.

        :param param:
        :return:
        """
        if "virtual_sdcard" not in param:
            return
        is_active = param["virtual_sdcard"].get("is_active", None)
        if is_active is not None and not is_active:
            if self._printing_file is not None:
                self._printing_file.close()
                self._printing_file = None
                _logger.info("Done printing, closing file.")
                return

        file_path = param["virtual_sdcard"].get("file_path", None)
        if self._printing_file is None and file_path is not None:
            self._printing_file = motion_minder.GCodeReader(file_path)
            _logger.info("Found a new file, starting to read it.")
        elif self._printing_file is None:
            virtual_sdcard = self._motion_minder.get_obj("virtual_sdcard")
            file_path = virtual_sdcard.get("file_path", None)
            if file_path is None:
                return
            self._printing_file = motion_minder.GCodeReader(file_path)
            _logger.info("Found a running file, starting to read it.")
        file_position = param["virtual_sdcard"].get("file_position", -1)
        distances = self._printing_file.read(file_position=file_position)
        distances.pop("e", None)
        for axis, value in distances.items():
            self._diff_dist[axis] += value

    def on_message(self, message: dict) -> None:
        """
        Process the message received from the websocket.

        :param message: The message received from the websocket.
        :return:
        """
        params = message.get("params", [])

        callbacks = [
            self._process_motion_report,
            self._process_toolhead,
            self._process_virtual_sdcard,
            self._check_update_db_odometer,
        ]
        for param in params:
            if not isinstance(param, dict):
                continue
            for callback in callbacks:
                try:
                    callback(param)
                except Exception as e:
                    _logger.error(
                        f"Error while processing message: {param}. Error: {e}",
                        exc_info=True,
                    )


if __name__ == "__main__":
    p = PrinterOdometer(
        moonraker_address=motion_minder.MOONRAKER_ADDRESS,
        namespace=motion_minder.NAMESPACE,
    )
    while True:
        time.sleep(60)
