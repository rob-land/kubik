"""Giiker / Xiaomi Mi Smart Magic Cube.

The GoCube binary drives these too — `GoCubeParser` carries an `isGiiker`
flag and hands off to `CubeGiikerMsgParser.ParseMsgGiiker` — and the
0000aadb/0000aadc pair turns up in all three Particula apps.

The notification is a 20-byte packet read as 40 nibbles: eight corner
positions, eight corner orientations, twelve edge positions, twelve edge
orientation bits, then the last four moves.
"""

from __future__ import annotations

import logging

from kubik.ble.driver import CubeDriver, register

log = logging.getLogger(__name__)

#: Giiker's face numbering, 1-based, mapped onto our URFDLB letters.
_FACES = {1: "B", 2: "D", 3: "L", 4: "U", 5: "R", 6: "F"}


@register
class Giiker(CubeDriver):
    id = "giiker"
    label = "Giiker / Mi Smart Cube"
    services = ("0000aadb-0000-1000-8000-00805f9b34fb",)
    notify_uuid = "0000aadc-0000-1000-8000-00805f9b34fb"
    name_prefixes = ("Gi", "Mi Smart Magic Cube", "GiC")
    reports_state = False

    def __init__(self, peripheral):
        super().__init__(peripheral)
        self._first = True

    def start(self):
        self.peripheral.subscribe(self.notify_uuid, self._on_data)

    def _on_data(self, data: bytes):
        if len(data) < 18:
            return
        nibbles = []
        for byte in data:
            nibbles.append(byte >> 4)
            nibbles.append(byte & 0x0F)
        # The first notification after connecting is the current state, not a
        # move; replaying it would inject a phantom turn.
        if self._first:
            self._first = False
            return
        face = _FACES.get(nibbles[32])
        amount = nibbles[33]
        if face is None:
            return
        self.emit_move(face, 3 if amount == 3 else 1)
