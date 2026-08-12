"""The live cube: whatever is driving it, plus the state the app believes in.

Both connected hardware and the on-screen cube feed this. Keeping one object
in front of the UI means every view — course, timer, play — works identically
whether or not a cube is plugged in.
"""

from __future__ import annotations

import logging

from gi.repository import GObject

from kubik.cube import Cube, Cube2, format_move
from kubik.ble import gan, giiker, gocube  # noqa: F401  (registers the drivers)
from kubik.ble.bluez import Central
from kubik.ble.driver import identify, scan_filter

log = logging.getLogger(__name__)


class Session(GObject.Object):
    """Owns the connection and the believed cube state."""

    __gtype_name__ = "KubikSession"

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "moved": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "status": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "connection": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    connected = GObject.Property(type=bool, default=False)
    cube_type = GObject.Property(type=str, default="3x3")
    device_name = GObject.Property(type=str, default="")
    battery = GObject.Property(type=int, default=-1)
    hardware = GObject.Property(type=str, default="")

    def __init__(self):
        super().__init__()
        self.cube = Cube()
        self.central = Central()
        self.driver = None
        self._history: list[str] = []

    # -- state ------------------------------------------------------------

    @property
    def size(self) -> int:
        return 2 if self.cube_type == "2x2" else 3

    def set_puzzle(self, cube_type: str):
        """Switch between the 3x3 and the 2x2, resetting the model."""
        if cube_type == self.cube_type:
            return
        self.cube_type = cube_type
        self.reset()

    @property
    def history(self) -> list[str]:
        return list(self._history)

    def reset(self, cube=None):
        if cube is not None:
            self.cube = cube.copy()
        else:
            self.cube = Cube2() if self.cube_type == "2x2" else Cube()
        self._history.clear()
        self.emit("changed")

    def apply_move(self, move: str, *, record: bool = True):
        self.cube.turn(move)
        if record:
            self._history.append(move)
        self.emit("moved", move)
        self.emit("changed")

    def apply_sequence(self, seq):
        from ..cube import tokenize

        for move in tokenize(seq):
            self.apply_move(move)

    # -- scanning ----------------------------------------------------------

    def start_scan(self) -> bool:
        if self.central.bus is None and not self.central.start():
            return False
        if not self.central.powered():
            self.central.set_powered(True)
        self.central.start_discovery(scan_filter())
        return True

    def stop_scan(self):
        self.central.stop_discovery()

    # -- connecting --------------------------------------------------------

    def connect_cube(self, device):
        def ready(peripheral):
            cls = identify(peripheral.name, peripheral.uuids()) \
                or identify(device.name, device.uuids)
            if cls is None:
                self.emit("status", "That device is not a cube this app knows.")
                peripheral.disconnect()
                return
            driver = cls(peripheral)
            driver.connect("move", self._on_move)
            driver.connect("state", self._on_state)
            driver.connect("battery", self._on_battery)
            driver.connect("hardware", self._on_hardware)
            driver.connect("unsupported", self._on_unsupported)
            self.driver = driver
            self.set_puzzle(cls.cube_type)
            self.device_name = device.name or cls.label
            self.connected = True
            self.emit("connection", True)
            self.emit("status", f"Connected to {self.device_name}.")
            try:
                driver.start()
            except Exception as err:  # a missing characteristic, usually
                log.exception("driver start failed")
                self.emit("status", f"Could not start the cube: {err}")

        def failed(message):
            self.emit("status", f"Connection failed: {message}")

        self.central.stop_discovery()
        self.central.connect_device(device, ready, failed)

    def disconnect_cube(self):
        if self.driver is not None:
            self.driver.stop()
            self.driver = None
        self.connected = False
        self.device_name = ""
        self.battery = -1
        self.hardware = ""
        self.emit("connection", False)

    # -- driver callbacks --------------------------------------------------

    def _on_move(self, _driver, face: str, quarters: int):
        self.apply_move(format_move(face, quarters))

    def _on_state(self, _driver, payload):
        try:
            cube = _cube_from_payload(payload)
        except Exception:
            log.exception("could not read the reported cube state")
            return
        if getattr(cube, "size", 3) != self.size:
            self.cube_type = "2x2" if cube.size == 2 else "3x3"
        self.cube = cube
        self.emit("changed")

    def _on_battery(self, _driver, level: int):
        self.battery = level

    def _on_hardware(self, _driver, text: str):
        self.hardware = text

    def _on_unsupported(self, _driver, text: str):
        self.emit("status", text)


def _cube_from_payload(payload):
    """Accept a (cp, co, ep, eo) tuple, or 54 facelets, or 24."""
    if isinstance(payload, tuple) and len(payload) == 4:
        cube = Cube(*payload)
        cube.validate()
        return cube
    facelets = list(payload)
    if len(facelets) == 24:
        return Cube2.from_facelets(facelets)
    return Cube.from_facelets(facelets)
