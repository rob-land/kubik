"""Smart-cube driver contract and registry.

Every supported cube reports **moves** reliably; only some report an absolute
facelet state, and the encodings for that vary far more than the move stream
does. So a driver is only required to emit moves, and the session seeds its
model from an explicit "my cube is solved" sync — which is how GoCube's own app
works too (`Cube must be in a solved state to start`). Drivers that can report
absolute state emit `state` as well and the session prefers it.
"""

from __future__ import annotations

import logging

from gi.repository import GObject

log = logging.getLogger(__name__)


class BitReader:
    """MSB-first bit reader; GAN packs its fields this way."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, width: int) -> int:
        value = 0
        for _ in range(width):
            byte = self.data[self.pos >> 3] if self.pos >> 3 < len(self.data) else 0
            value = (value << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return value

    def skip(self, width: int):
        self.pos += width


class BitWriter:
    def __init__(self, length: int):
        self.data = bytearray(length)
        self.pos = 0

    def write(self, width: int, value: int):
        for i in range(width - 1, -1, -1):
            if (value >> i) & 1:
                self.data[self.pos >> 3] |= 1 << (7 - (self.pos & 7))
            self.pos += 1


class CubeDriver(GObject.Object):
    """Base class. Subclasses decode one vendor's notifications."""

    __gtype_name__ = "KubikCubeDriver"

    #: Stable identifier used in settings and in the device list.
    id = "base"
    #: Human-readable family name.
    label = "Cube"
    #: Service UUIDs to pass to BlueZ as a scan filter.
    services: tuple[str, ...] = ()
    #: Advertised-name prefixes, matched case-insensitively.
    name_prefixes: tuple[str, ...] = ()
    #: False when the family is recognised but its packets are not decoded.
    implemented = True
    #: True when the driver can report an absolute facelet state.
    reports_state = False
    #: Which puzzle this family is, so the session can switch to match.
    cube_type = "3x3"

    __gsignals__ = {
        # face letter, quarter turns (1 or 3)
        "move": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
        # 54 facelet colour indices
        "state": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "battery": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "hardware": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "unsupported": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, peripheral):
        super().__init__()
        self.peripheral = peripheral

    @classmethod
    def matches(cls, name: str, uuids) -> bool:
        lowered = {u.lower() for u in uuids}
        if any(s.lower() in lowered for s in cls.services):
            return True
        name = (name or "").lower()
        return any(name.startswith(p.lower()) for p in cls.name_prefixes)

    def start(self):
        """Subscribe to notifications and request an initial state."""
        raise NotImplementedError

    def stop(self):
        self.peripheral.disconnect()

    def request_state(self):
        """Ask the cube to re-send its absolute state, if it can."""

    # -- helpers for subclasses ----------------------------------------

    def emit_move(self, face: str, quarters: int):
        self.emit("move", face, quarters)


# --- registry ---------------------------------------------------------------

_REGISTRY: list[type[CubeDriver]] = []


def register(cls: type[CubeDriver]) -> type[CubeDriver]:
    _REGISTRY.append(cls)
    return cls


def drivers() -> list[type[CubeDriver]]:
    return list(_REGISTRY)


def identify(name: str, uuids) -> type[CubeDriver] | None:
    """Pick a driver, preferring the most specific advertised-name match.

    Families share transports — GoCube and GoCube 2x2 both advertise the same
    Nordic UART service — so the name has to win over the service UUID, and a
    longer prefix has to win over a shorter one.
    """
    lowered = (name or "").lower()
    by_prefix = []
    for cls in _REGISTRY:
        for prefix in cls.name_prefixes:
            if lowered.startswith(prefix.lower()):
                by_prefix.append((len(prefix), cls))
    if by_prefix:
        return max(by_prefix, key=lambda item: item[0])[1]
    services = {u.lower() for u in uuids}
    for cls in _REGISTRY:
        if any(s.lower() in services for s in cls.services):
            return cls
    return None


def scan_filter() -> list[str]:
    seen: list[str] = []
    for cls in _REGISTRY:
        for service in cls.services:
            if service not in seen:
                seen.append(service)
    return seen
