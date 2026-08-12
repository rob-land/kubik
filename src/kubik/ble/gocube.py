"""GoCube, Rubik's Connected and GoCube 2x2 (Particula).

All three ship the same binary — the localization assets are byte-identical
between `com.particula.gocube` and `com.particula.rubiksconnected` — and it
talks over a Nordic UART Service. The framing below follows the fields
recovered from `GoCubeParser` in the IL2CPP metadata:

    PrefixLength  FirstLetter                 -> 0x2A '*'
    msgLength                                 -> length byte
    ParseContents                             -> type byte + payload
    ChecksumLength                            -> one byte
    SuffixLength  PreLastLetter  LastLetter   -> 0x0D 0x0A

and the message types are its Parse* methods: RotatingSide,
CubeColorAndDirectionState, Quaternion, BatteryLevel, OfflineStats,
IsEdgeCube, CubeInfo.
"""

from __future__ import annotations

import logging

from kubik.ble.driver import CubeDriver, register

log = logging.getLogger(__name__)

PREFIX = 0x2A
SUFFIX = b"\x0d\x0a"

MSG_ROTATION = 0x01
MSG_STATE = 0x02
MSG_QUATERNION = 0x03
MSG_BATTERY = 0x05
MSG_OFFLINE_STATS = 0x07
MSG_CUBE_TYPE = 0x08

#: GoCube numbers its faces B F U D R L, two codes per face (cw, ccw).
_FACES = "BFUDRL"

#: Its colour indices, mapped onto our URFDLB face order.
_COLOR_TO_FACE = {0: 5, 1: 2, 2: 0, 3: 3, 4: 1, 5: 4}

#: GoCube reports its 54 stickers face by face in B F U D R L order.
_FACE_ORDER = [5, 2, 0, 3, 1, 4]


@register
class GoCube(CubeDriver):
    id = "gocube"
    label = "GoCube / Rubik's Connected"
    services = ("6e400001-b5a3-f393-e0a9-e50e24dcca9e",)
    notify_uuid = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
    write_uuid = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
    name_prefixes = ("GoCube", "Rubiks", "Rubik's")
    reports_state = True

    def __init__(self, peripheral):
        super().__init__(peripheral)
        self._buffer = bytearray()

    def start(self):
        self.peripheral.subscribe(self.notify_uuid, self._on_data)
        self.request_state()

    def request_state(self):
        # Single-byte commands: 0x32 state, 0x33 battery, 0x35 cube type.
        for command in (0x32, 0x33, 0x35):
            self.peripheral.write(self.write_uuid, bytes([command]))

    # -- framing ---------------------------------------------------------

    def _on_data(self, chunk: bytes):
        self._buffer.extend(chunk)
        while True:
            start = self._buffer.find(PREFIX)
            if start < 0:
                self._buffer.clear()
                return
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 3:
                return
            length = self._buffer[1]
            # length counts prefix + length + payload + checksum.
            total = length + len(SUFFIX)
            if length < 3 or len(self._buffer) < total:
                return
            frame = bytes(self._buffer[:total])
            del self._buffer[:total]
            if frame[-2:] != SUFFIX:
                log.debug("GoCube frame without CRLF: %s", frame.hex())
                continue
            body = frame[2:length - 1]
            checksum = frame[length - 1]
            if (sum(frame[:length - 1]) & 0xFF) != checksum:
                log.debug("GoCube checksum mismatch: %s", frame.hex())
                continue
            self._dispatch(body[0], body[1:])

    def _dispatch(self, kind: int, payload: bytes):
        if kind == MSG_ROTATION and len(payload) >= 1:
            code = payload[0]
            if code >> 1 < len(_FACES):
                self.emit_move(_FACES[code >> 1], 3 if code & 1 else 1)
        elif kind == MSG_STATE:
            # `CubeUtilities.CubeTypeFromFullStateMessage` in the 2x2 build
            # tells the puzzle apart by how long this payload is: nine
            # stickers per face, or four.
            for stickers in (9, 4):
                if len(payload) >= 6 * stickers:
                    self._emit_state(payload, stickers)
                    break
        elif kind == MSG_BATTERY and payload:
            self.emit("battery", payload[0])
        elif kind == MSG_CUBE_TYPE and payload:
            self.emit("hardware", f"GoCube type 0x{payload[0]:02x}")

    def _emit_state(self, payload: bytes, stickers: int = 9):
        facelets = [0] * (6 * stickers)
        for slot, face in enumerate(_FACE_ORDER):
            for i in range(stickers):
                colour = payload[slot * stickers + i]
                facelets[face * stickers + i] = _COLOR_TO_FACE.get(colour, 0)
        self.emit("state", facelets)


@register
class GoCube2x2(GoCube):
    """Same binary, same transport, same framing — four stickers per face.

    The 2x2 build's `GoCubeParser` has members identical to the 3x3's, so the
    rotation messages and the frame layout are shared; only the length of the
    full-state payload differs.
    """

    id = "gocube-2x2"
    label = "GoCube 2x2"
    name_prefixes = ("GoCube2", "GC2")
    cube_type = "2x2"
    reports_state = True
