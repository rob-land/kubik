"""GAN smart cubes.

The Gen2 bit layout below is not guessed: CubeStation ships a readable Vue
bundle whose `LogicCubeParse` is a straight bit-field reader, and the field
widths here are transcribed from it —

    type 1  GYRO      (1,15) x4 quaternion, (1,3) x3 velocity
    type 2  MOVES     8 serial, (5) x7 move codes, (16) x7 timings
    type 4  FACELETS  8 serial, (3) x7 CP, (2) x7 CO, (4) x11 EP, (1) x11 EO
    type 5  HARDWARE  4 pad, 8x4 versions, 8x8 name, gyro flag
    type 9  BATTERY   4 pad, 8 level

CubeStation's own `devicedata_cn.json` maps its 32 supported products onto
three protocol generations, which it numbers 1/2/3 — one less than the
community's Gen2/Gen3/Gen4 naming for the same three protocols.
"""

from __future__ import annotations

import logging

from kubik.ble.aes import AES128, cbc_decrypt_block, cbc_encrypt_block
from kubik.ble.driver import BitReader, BitWriter, CubeDriver, register

log = logging.getLogger(__name__)

#: GAN's two key/IV pairs. Index 0 serves Gen2, index 1 Gen3 and Gen4.
_KEYS = [
    (bytes([0x01, 0x02, 0x42, 0x28, 0x31, 0x91, 0x16, 0x07,
            0x20, 0x05, 0x18, 0x54, 0x42, 0x11, 0x12, 0x53]),
     bytes([0x11, 0x03, 0x32, 0x28, 0x21, 0x01, 0x76, 0x27,
            0x20, 0x95, 0x78, 0x14, 0x32, 0x12, 0x02, 0x79])),
    (bytes([0x05, 0x12, 0x02, 0x45, 0x02, 0x01, 0x29, 0x56,
            0x12, 0x78, 0x12, 0x76, 0x81, 0x01, 0x08, 0x03]),
     bytes([0x01, 0x44, 0x28, 0x06, 0x86, 0x21, 0x22, 0x28,
            0x51, 0x05, 0x08, 0x31, 0x55, 0x08, 0x32, 0x82])),
]

#: GAN's face order for 5-bit move codes.
_FACES = "URFDLB"


class _Encrypter:
    """AES-128-CBC over the head and tail blocks, keyed by the MAC."""

    def __init__(self, index: int, address: str):
        key, iv = _KEYS[index]
        salt = _salt_from_address(address)
        self.key = bytes((key[i] + salt[i]) % 0xFF if i < 6 else key[i]
                         for i in range(16))
        self.iv = bytes((iv[i] + salt[i]) % 0xFF if i < 6 else iv[i]
                        for i in range(16))
        self.cipher = AES128(self.key)

    def decrypt(self, data: bytes) -> bytes:
        buf = bytearray(data)
        if len(buf) > 16:
            self._chunk(buf, len(buf) - 16, decrypt=True)
        self._chunk(buf, 0, decrypt=True)
        return bytes(buf)

    def encrypt(self, data: bytes) -> bytes:
        buf = bytearray(data)
        self._chunk(buf, 0, decrypt=False)
        if len(buf) > 16:
            self._chunk(buf, len(buf) - 16, decrypt=False)
        return bytes(buf)

    def _chunk(self, buf, offset, decrypt):
        block = bytes(buf[offset:offset + 16])
        fn = cbc_decrypt_block if decrypt else cbc_encrypt_block
        buf[offset:offset + 16] = fn(self.cipher, self.iv, block)


def _salt_from_address(address: str) -> bytes:
    """The last six MAC bytes, reversed — GAN's key derivation salt."""
    parts = [int(p, 16) for p in address.split(":")] if address else []
    if len(parts) != 6:
        raise ValueError(f"cannot derive a GAN key from address {address!r}")
    return bytes(reversed(parts))


class _GanDriver(CubeDriver):
    key_index = 0
    notify_uuid = ""
    write_uuid = ""

    def __init__(self, peripheral):
        super().__init__(peripheral)
        self.crypto = _Encrypter(self.key_index, peripheral.address)
        self._last_serial: int | None = None

    def start(self):
        self.peripheral.subscribe(self.notify_uuid, self._on_packet)
        self.request_state()

    def _on_packet(self, raw: bytes):
        try:
            packet = self.crypto.decrypt(raw)
        except Exception:
            log.exception("GAN decryption failed")
            return
        self.handle(packet)

    def handle(self, packet: bytes):
        raise NotImplementedError

    def _send(self, payload: bytes):
        self.peripheral.write(self.write_uuid, self.crypto.encrypt(payload))


@register
class GanGen2(_GanDriver):
    """GAN356 i family, GAN12 ui, GAN i carry S — CubeStation's `proto: 1`."""

    id = "gan-gen2"
    label = "GAN (Gen2)"
    key_index = 0
    services = ("6e400001-b5a3-f393-e0a9-e50e24dc4179",)
    notify_uuid = "28be4cb6-cd67-11e9-a32f-2a2ae2dbcce4"
    write_uuid = "28be4a4a-cd67-11e9-a32f-2a2ae2dbcce4"
    # Straight out of CubeStation's devicedata_cn.json, every product it lists
    # with `proto: 1`. No bare "GAN" prefix: that would swallow the Gen3 and
    # Gen4 cubes, which are told apart from these by longer prefixes.
    name_prefixes = ("GAN SmartCube", "GAN356I", "GAN356i", "GAN356i-Lite",
                     "GAN356iV1.1.3", "GAN356iplay2", "GAN ROBOT",
                     "GAN Timer", "GAN i3", "GAN 12ui", "GAN12ui",
                     "GAN12uiFp", "GANminiuiFp", "GANicS", "XES", "MG3 Ai")
    reports_state = True

    EVENT_GYRO = 1
    EVENT_MOVES = 2
    EVENT_FACELETS = 4
    EVENT_HARDWARE = 5
    EVENT_BATTERY = 9
    EVENT_DISCONNECT = 13

    def request_state(self):
        self._request(self.EVENT_FACELETS)
        self._request(self.EVENT_HARDWARE)
        self._request(self.EVENT_BATTERY)

    def _request(self, opcode: int):
        writer = BitWriter(20)
        writer.write(4, opcode)
        self._send(bytes(writer.data))

    def handle(self, packet: bytes):
        reader = BitReader(packet)
        event = reader.read(4)
        if event == self.EVENT_MOVES:
            self._handle_moves(reader)
        elif event == self.EVENT_FACELETS:
            self._handle_facelets(reader)
        elif event == self.EVENT_BATTERY:
            reader.skip(4)
            self.emit("battery", reader.read(8))
        elif event == self.EVENT_HARDWARE:
            self._handle_hardware(reader)

    def _handle_moves(self, reader: BitReader):
        serial = reader.read(8)
        codes = [reader.read(5) for _ in range(7)]
        # The cube always sends its last seven moves. The first packet after
        # connecting is history, not news — record the serial and replay
        # nothing, or the session picks up a phantom turn.
        first = self._last_serial is None
        fresh = 0 if first else (serial - self._last_serial) & 0xFF
        self._last_serial = serial
        for i in reversed(range(min(fresh, 7))):
            code = codes[i]
            face = _FACES[code >> 1]
            self.emit_move(face, 3 if code & 1 else 1)

    def _handle_facelets(self, reader: BitReader):
        reader.read(8)  # serial
        cp = [reader.read(3) for _ in range(7)]
        co = [reader.read(2) for _ in range(7)]
        ep = [reader.read(4) for _ in range(11)]
        eo = [reader.read(1) for _ in range(11)]
        cp.append(28 - sum(cp))
        co.append((3 - sum(co) % 3) % 3)
        ep.append(66 - sum(ep))
        eo.append(sum(eo) % 2)
        self.emit("state", (cp, co, ep, eo))

    def _handle_hardware(self, reader: BitReader):
        reader.skip(4)
        hw_major, hw_minor = reader.read(8), reader.read(8)
        sw_major, sw_minor = reader.read(8), reader.read(8)
        name = "".join(chr(reader.read(8)) for _ in range(8)).strip("\0 ")
        self.emit("hardware",
                  f"{name} — hardware {hw_major}.{hw_minor}, "
                  f"firmware {sw_major}.{sw_minor}")


class _GanUndecoded(_GanDriver):
    """Recognised, connectable, but the packet layout is not implemented.

    The UUIDs and the key derivation are right — those came out of
    CubeStation's device table and its shared crypto — but the bit layouts for
    these two generations live in the AES-ECB `GanSDK_Protocol*.alpha` blobs,
    which this teardown did not break. Rather than ship a decoder built on
    recollection, the driver connects and says so.
    """

    implemented = False

    def start(self):
        self.emit("unsupported",
                  f"{self.label} cubes are recognised but their packet format "
                  f"is not decoded yet. Use the on-screen cube for now.")

    def handle(self, packet: bytes):
        log.debug("%s packet: %s", self.id, packet.hex())


@register
class GanGen3(_GanUndecoded):
    """GAN i carry 2 — CubeStation's `proto: 2`."""

    id = "gan-gen3"
    label = "GAN (Gen3)"
    key_index = 1
    services = ("8653000a-43e6-47b7-9cb0-5fc21d4ae340",)
    notify_uuid = "8653000b-43e6-47b7-9cb0-5fc21d4ae340"
    write_uuid = "8653000c-43e6-47b7-9cb0-5fc21d4ae340"
    name_prefixes = ("GANicV2S", "icV2S")


@register
class GanGen4(_GanDriver):
    """GAN12 ui Maglev, GAN14 ui, i carry E/4 — CubeStation's `proto: 3`.

    Decoded against a GAN i Carry 4. The plaintext is a run of type/length/
    value records packed into the 20-byte frame, terminated by a zero type or
    an empty 0x3A, with two trailing bytes and a two-byte trailer::

        01 07 <u32le ms> <u16le serial> <move>     a turn
        02 04 <u32le ms>                           that turn completed
        ED 0E <u16le serial> <12 bytes>            cube state, one per turn
        EF 01 <percent>                            battery
        3A 00                                      end of list

    A move byte is a one-hot face in bits 0-5 with bit 6 set for anticlockwise.
    Two details here contradict what the community documents for this
    generation, and both were confirmed on hardware: `fff6` notifies while
    `fff5` takes writes, and the cipher uses key index 0 rather than 1.
    """

    id = "gan-gen4"
    label = "GAN (Gen4)"
    key_index = 0
    services = ("00000010-0000-fff7-fff6-fff5fff4fff0",)
    notify_uuid = "0000fff6-0000-1000-8000-00805f9b34fb"
    write_uuid = "0000fff5-0000-1000-8000-00805f9b34fb"
    name_prefixes = ("GAN12uiM", "GAN12uiM2", "GANicE", "GANicE2",
                     "GAN12uiFp2", "GAN14ui", "GAN14 ui", "GAN12i",
                     "GANi3v2", "GANi3V2", "GAN i4", "GANi4v2", "GANic4",
                     "GANic251", "GAN251ui", "GAN00")

    MSG_MOVE = 0x01
    MSG_MOVE_DONE = 0x02
    MSG_STATE = 0xED
    MSG_BATTERY = 0xEF
    MSG_END = 0x3A

    #: Bit position within the move byte, in face order.
    FACES = "FBUDRL"

    reports_state = True

    # The 12-byte state body: 7x3 corner slots, 8x2 corner twists, 11x4 edge
    # slots, 12x1 edge flips, three spare bits. The eighth corner and twelfth
    # edge are recovered by elimination.
    #
    # GAN numbers its slots and its pieces differently from the URFDLB order
    # this app uses, and measures orientation against its own reference
    # sticker. All four tables below were fitted to 164 states captured from a
    # GAN i Carry 4 whose every move was known, and reproduce all of them.
    CORNER_SLOTS = (6, 7, 3, 2, 5, 4, 0, 1)
    EDGE_SLOTS = (10, 7, 11, 3, 9, 5, 8, 1, 6, 4, 0, 2)
    CORNER_CUBIE = (3, 6, 0, 4, 5, 2, 7, 1)
    EDGE_CUBIE = (0, 11, 8, 6, 2, 9, 4, 5, 10, 3, 7, 1)
    # Orientation is the reported value plus a per-piece offset, and the slots
    # fall into two classes whose references differ by one further step.
    TWIST_BASE = (2, 1, 2, 0, 0, 2, 1, 0)
    TWIST_ALT_SLOTS = frozenset({0, 2, 5, 7})
    FLIP_BASE = (1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 1, 0)
    FLIP_ALT_SLOTS = frozenset({0, 1, 2, 3, 4, 5, 7})

    #: The cube replays its recent history on connect; ignore that burst so a
    #: freshly connected session does not pick up turns from minutes ago.
    PRIME_DELAY_MS = 1500

    def __init__(self, peripheral):
        super().__init__(peripheral)
        self._primed = False
        self._last_ts: int | None = None

    def start(self):
        from gi.repository import GLib

        self.peripheral.subscribe(self.notify_uuid, self._on_packet)
        GLib.timeout_add(self.PRIME_DELAY_MS, self._prime)

    def _prime(self):
        self._primed = True
        return False

    def handle(self, packet: bytes):
        for kind, payload in records(packet):
            if kind == self.MSG_MOVE and len(payload) >= 7:
                self._handle_move(payload)
            elif kind == self.MSG_BATTERY and payload:
                self.emit("battery", payload[0])
            elif kind == self.MSG_STATE and len(payload) >= 14:
                self._handle_state(payload[2:14])

    def _handle_state(self, body: bytes):
        reader = BitReader(body)
        slots = [reader.read(3) for _ in range(7)]
        twists = [reader.read(2) for _ in range(8)]
        edges = [reader.read(4) for _ in range(11)]
        flips = [reader.read(1) for _ in range(12)]

        cp, co = [0] * 8, [0] * 8
        ep, eo = [0] * 12, [0] * 12
        for i, value in enumerate(slots):
            cp[self.CORNER_SLOTS[i]] = self.CORNER_CUBIE[value]
        cp[self.CORNER_SLOTS[7]] = 28 - sum(cp)
        for i, value in enumerate(edges):
            ep[self.EDGE_SLOTS[i]] = self.EDGE_CUBIE[value]
        ep[self.EDGE_SLOTS[11]] = 66 - sum(ep)

        for i, value in enumerate(twists):
            slot = self.CORNER_SLOTS[i]
            extra = 1 if slot in self.TWIST_ALT_SLOTS else 0
            co[slot] = (value + self.TWIST_BASE[cp[slot]] + extra) % 3
        for i, value in enumerate(flips):
            slot = self.EDGE_SLOTS[i]
            extra = 1 if slot in self.FLIP_ALT_SLOTS else 0
            eo[slot] = (value + self.FLIP_BASE[ep[slot]] + extra) % 2
        self.emit("state", (cp, co, ep, eo))

    def _handle_move(self, payload: bytes):
        """Order and de-duplicate on the cube's own clock, not on the serial.

        Every notification is delivered several times over, and the history
        replayed at connect carries serials that collide with turns still to
        come — the serial wraps well inside one session, the millisecond clock
        does not.
        """
        timestamp = int.from_bytes(payload[0:4], "little")
        code = payload[6]
        if self._last_ts is not None and timestamp <= self._last_ts:
            return
        self._last_ts = timestamp
        if not self._primed:
            return
        face = code & 0x3F
        if face == 0 or face & (face - 1):
            log.debug("unexpected GAN move byte 0x%02x", code)
            return
        self.emit_move(self.FACES[face.bit_length() - 1],
                       3 if code & 0x40 else 1)


def records(packet: bytes, limit: int = 18):
    """Walk the type/length/value records in a decrypted GAN Gen4 frame."""
    pos = 0
    while pos + 2 <= limit:
        kind, length = packet[pos], packet[pos + 1]
        if kind == 0 or pos + 2 + length > limit:
            return
        yield kind, packet[pos + 2:pos + 2 + length]
        pos += 2 + length
    # `proto: 3` in the same table. Several of these extend a Gen2 prefix
    # ("GAN12uiFp2" over "GAN12uiFp"), which is why identify() resolves by
    # longest match rather than registration order.
    name_prefixes = ("GAN12uiM", "GAN12uiM2", "GANicE", "GANicE2",
                     "GAN12uiFp2", "GAN14ui", "GAN14 ui", "GAN12i",
                     "GANi3v2", "GANi3V2", "GAN i4", "GANi4v2", "GANic4",
                     "GANic251", "GAN251ui", "GAN00")
