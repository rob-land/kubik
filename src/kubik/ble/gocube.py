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

#: Within a face the centre comes first, then the eight ring stickers
#: clockwise — not the row-major order the net is drawn in. Expressed as
#: row-major positions, the ring is:
_RING = (0, 1, 2, 5, 8, 7, 6, 3)

#: The cube walks each ring from its own reference corner. Flattened into the
#: net, the four side faces line up but U and D come out rotated a quarter
#: turn each, so they start two steps round the ring in opposite directions.
#: Solved against a Rubik's Connected X: a solved cube cannot show any of
#: this, because every self-consistent relabelling decodes solved as solved.
_RING_START = {0: 6, 1: 0, 2: 0, 3: 2, 4: 0, 5: 0}


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

    #: Single-byte requests, confirmed against a Rubik's Connected X.
    #: 0x33 answers with a state message (type 0x02, 54 facelets plus six
    #: trailing bytes) and 0x32 with battery (type 0x05). 0x37 draws no
    #: response. 0x35 also answers with a state message but is *not* sent:
    #: after a run that ended with it, the cube reported a solved state while
    #: physically scrambled, so it plausibly resets the cube's tracking.
    #: Nothing here needs it, and sending an unidentified command that may
    #: wipe a solve in progress is not a trade worth making.
    REQUEST_STATE = 0x33
    REQUEST_BATTERY = 0x32

    def request_state(self):
        for command in (self.REQUEST_STATE, self.REQUEST_BATTERY):
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
        elif kind == MSG_STATE and len(payload) >= 54:
            self._emit_state(payload)
        elif kind == MSG_BATTERY and payload:
            self.emit("battery", payload[0])
        elif kind == MSG_CUBE_TYPE and payload:
            self.emit("hardware", f"GoCube type 0x{payload[0]:02x}")

    def _emit_state(self, payload: bytes):
        facelets = [0] * 54
        for group, face in enumerate(_FACE_ORDER):
            base = group * 9
            facelets[face * 9 + 4] = _COLOR_TO_FACE.get(payload[base], 0)
            start = _RING_START[face]
            for step in range(8):
                position = _RING[(start + step) % 8]
                colour = payload[base + 1 + step]
                facelets[face * 9 + position] = _COLOR_TO_FACE.get(colour, 0)
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
    # Moves only. The 3x3's state payload turned out to be centre-first then a
    # clockwise ring, with U and D rotated a quarter turn — none of which is
    # guessable, and none of which a 2x2 (no centres) can share. Rather than
    # emit a state decoded on an assumption, this family reports turns and the
    # session tracks from a sync.
    reports_state = False
