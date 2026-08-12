"""Crypto, framing and driver selection.

The radio side cannot be exercised without hardware, so what is tested here is
everything up to the radio: the cipher against published vectors, the packet
decoders against synthetic packets built by the matching encoder, and the
driver registry against the advertised names the teardown recovered.
"""

import collections
import itertools
import pathlib

import pytest

from kubik.ble import gan, gocube  # noqa: F401  (registers drivers)
from kubik.ble.aes import AES128
from kubik.ble.driver import BitReader, BitWriter, identify
from kubik.ble.gan import GanGen2, GanGen3, GanGen4, _Encrypter
from kubik.ble.giiker import Giiker
from kubik.ble.gocube import GoCube, GoCube2x2


# --- AES --------------------------------------------------------------------

@pytest.mark.parametrize("key,plain,cipher", [
    ("000102030405060708090a0b0c0d0e0f",
     "00112233445566778899aabbccddeeff",
     "69c4e0d86a7b0430d8cdb78070b4c55a"),
    ("2b7e151628aed2a6abf7158809cf4f3c",
     "3243f6a8885a308d313198a2e0370734",
     "3925841d02dc09fbdc118597196a0b32"),
])
def test_aes128_fips197(key, plain, cipher):
    aes = AES128(bytes.fromhex(key))
    assert aes.encrypt_block(bytes.fromhex(plain)).hex() == cipher
    assert aes.decrypt_block(bytes.fromhex(cipher)).hex() == plain


def test_aes_rejects_short_keys():
    with pytest.raises(ValueError):
        AES128(b"tooshort")


# --- GAN packet crypto ------------------------------------------------------

ADDRESS = "AB:12:34:56:78:9A"


def test_gan_encrypt_decrypt_roundtrip():
    crypto = _Encrypter(0, ADDRESS)
    for payload in (bytes(range(20)), bytes(20), b"\xff" * 20):
        assert crypto.decrypt(crypto.encrypt(payload)) == payload


def test_gan_key_depends_on_the_mac():
    a = _Encrypter(0, ADDRESS)
    b = _Encrypter(0, "AB:12:34:56:78:9B")
    assert a.key != b.key and a.iv != b.iv


def test_gan_key_index_matters():
    assert _Encrypter(0, ADDRESS).key != _Encrypter(1, ADDRESS).key


def test_gan_rejects_a_bad_address():
    with pytest.raises(ValueError):
        _Encrypter(0, "not-a-mac")


# --- bit packing ------------------------------------------------------------

def test_bit_reader_is_msb_first():
    reader = BitReader(bytes([0b1010_0110]))
    assert reader.read(4) == 0b1010
    assert reader.read(4) == 0b0110


def test_bit_writer_matches_reader():
    writer = BitWriter(4)
    for width, value in ((4, 9), (5, 21), (3, 5), (8, 200)):
        writer.write(width, value)
    reader = BitReader(bytes(writer.data))
    assert [reader.read(w) for w in (4, 5, 3, 8)] == [9, 21, 5, 200]


def test_bit_reader_past_the_end_yields_zero():
    assert BitReader(b"\xff").read(16) == 0xFF00


# --- GAN Gen2 decoding ------------------------------------------------------

class FakePeripheral:
    def __init__(self, address=ADDRESS):
        self.address = address
        self.name = "GAN356i"
        self.written = []

    def subscribe(self, uuid, callback):
        self.callback = callback

    def write(self, uuid, data, response=False):
        self.written.append((uuid, data))

    def uuids(self):
        return [GanGen2.notify_uuid, GanGen2.write_uuid]

    def disconnect(self):
        pass


def _gen2_moves_packet(serial, codes):
    writer = BitWriter(20)
    writer.write(4, GanGen2.EVENT_MOVES)
    writer.write(8, serial)
    for code in codes:
        writer.write(5, code)
    return bytes(writer.data)


def test_gen2_decodes_moves_and_skips_history():
    driver = GanGen2(FakePeripheral())
    seen = []
    driver.connect("move", lambda _d, face, q: seen.append((face, q)))

    # First packet is the cube's history; nothing should be replayed.
    driver.handle(_gen2_moves_packet(5, [0, 0, 0, 0, 0, 0, 0]))
    assert seen == []

    # Serial advances by two: the two most recent codes, oldest first.
    # Code = face index << 1 | direction; 2 -> R, 7 -> D'.
    driver.handle(_gen2_moves_packet(7, [7, 2, 0, 0, 0, 0, 0]))
    assert seen == [("R", 1), ("D", 3)]


def test_gen2_decodes_battery():
    driver = GanGen2(FakePeripheral())
    levels = []
    driver.connect("battery", lambda _d, level: levels.append(level))
    writer = BitWriter(20)
    writer.write(4, GanGen2.EVENT_BATTERY)
    writer.write(4, 0)
    writer.write(8, 87)
    driver.handle(bytes(writer.data))
    assert levels == [87]


def test_gen2_decodes_a_solved_facelet_packet():
    """CP/CO/EP/EO with the last piece of each set derived by parity."""
    driver = GanGen2(FakePeripheral())
    states = []
    driver.connect("state", lambda _d, payload: states.append(payload))
    writer = BitWriter(20)
    writer.write(4, GanGen2.EVENT_FACELETS)
    writer.write(8, 1)
    for i in range(7):
        writer.write(3, i)
    for _ in range(7):
        writer.write(2, 0)
    for i in range(11):
        writer.write(4, i)
    for _ in range(11):
        writer.write(1, 0)
    driver.handle(bytes(writer.data))
    cp, co, ep, eo = states[0]
    assert cp == list(range(8))
    assert co == [0] * 8
    assert ep == list(range(12))
    assert eo == [0] * 12


def test_gen2_requests_are_encrypted_and_addressed():
    peripheral = FakePeripheral()
    driver = GanGen2(peripheral)
    driver.request_state()
    assert len(peripheral.written) == 3
    for uuid, data in peripheral.written:
        assert uuid == GanGen2.write_uuid
        assert len(data) == 20
        # Round-tripping recovers the 4-bit opcode.
        opcode = BitReader(driver.crypto.decrypt(data)).read(4)
        assert opcode in (GanGen2.EVENT_FACELETS, GanGen2.EVENT_HARDWARE,
                          GanGen2.EVENT_BATTERY)


# --- GoCube framing ---------------------------------------------------------

def _gocube_frame(kind, payload):
    length = 2 + 1 + len(payload)          # prefix, length, type, payload
    body = bytes([gocube.PREFIX, length + 1, kind]) + payload
    return body + bytes([sum(body) & 0xFF]) + gocube.SUFFIX


class FakeNus(FakePeripheral):
    def uuids(self):
        return [GoCube.notify_uuid, GoCube.write_uuid]


def test_gocube_decodes_a_rotation():
    driver = GoCube(FakeNus())
    seen = []
    driver.connect("move", lambda _d, face, q: seen.append((face, q)))
    # GoCube faces run B F U D R L, two codes each (clockwise, anticlockwise).
    driver._on_data(_gocube_frame(gocube.MSG_ROTATION, bytes([8])))   # R
    driver._on_data(_gocube_frame(gocube.MSG_ROTATION, bytes([5])))   # U'
    assert seen == [("R", 1), ("U", 3)]


def test_gocube_reassembles_split_notifications():
    driver = GoCube(FakeNus())
    seen = []
    driver.connect("move", lambda _d, face, q: seen.append((face, q)))
    frame = _gocube_frame(gocube.MSG_ROTATION, bytes([8]))
    driver._on_data(frame[:3])
    assert seen == []
    driver._on_data(frame[3:])
    assert seen == [("R", 1)]


def test_gocube_drops_a_corrupt_frame():
    driver = GoCube(FakeNus())
    seen = []
    driver.connect("move", lambda _d, face, q: seen.append((face, q)))
    frame = bytearray(_gocube_frame(gocube.MSG_ROTATION, bytes([8])))
    frame[-3] ^= 0xFF  # break the checksum
    driver._on_data(bytes(frame))
    assert seen == []


def test_gocube_decodes_battery():
    driver = GoCube(FakeNus())
    levels = []
    driver.connect("battery", lambda _d, level: levels.append(level))
    driver._on_data(_gocube_frame(gocube.MSG_BATTERY, bytes([64])))
    assert levels == [64]


# --- driver selection --------------------------------------------------------

@pytest.mark.parametrize("name,uuids,expected", [
    ("GAN356i-ABCD", [], GanGen2),
    ("GANicV2S_1234", [GanGen3.services[0]], GanGen3),
    ("GAN12uiM2_0001", [GanGen4.services[0]], GanGen4),
    ("GoCube-1234", [], GoCube),
    ("GoCube2x2-7", [], GoCube2x2),
    ("Rubiks-AA11", [], GoCube),
    ("Gi123456", [], Giiker),
    ("", [GoCube.services[0]], GoCube),
    ("", [Giiker.services[0]], Giiker),
    ("Some Headphones", ["0000110b-0000-1000-8000-00805f9b34fb"], None),
])
def test_identify(name, uuids, expected):
    assert identify(name, uuids) is expected


@pytest.mark.parametrize("name,expected", [
    # Pairs where one generation's prefix extends another's, taken from
    # CubeStation's device table. Longest match has to win.
    ("GAN12ui--123", GanGen2),
    ("GAN12uiM_0001", GanGen4),
    ("GAN12uiM2_0001", GanGen4),
    ("GAN12uiFP-123", GanGen2),
    ("GAN12uiFP2-123", GanGen4),
    ("GAN12i_0001", GanGen4),
    ("GANicS-123", GanGen2),
    ("GANicV2S_1234", GanGen3),
    ("GANicE_1234", GanGen4),
    ("GANicE2_1234", GanGen4),
    ("GANic4_1234", GanGen4),
    ("GAN i3", GanGen2),
    ("GANi3v2_1234", GanGen4),
])
def test_gan_prefix_collisions(name, expected):
    assert identify(name, []) is expected


def test_gan_generations_have_distinct_services():
    services = [GanGen2.services[0], GanGen3.services[0], GanGen4.services[0]]
    assert len(set(services)) == 3


def test_undecoded_families_are_flagged():
    for cls in (GanGen2, GanGen4, GoCube, GoCube2x2, Giiker):
        assert cls.implemented
    # Gen3 is the only family left undecoded: no hardware to test against.
    assert not GanGen3.implemented


def test_driver_puzzles():
    assert GoCube2x2.cube_type == "2x2"
    for cls in (GanGen2, GoCube, Giiker, GanGen3, GanGen4):
        assert cls.cube_type == "3x3"


def test_gocube_2x2_decodes_a_24_sticker_state():
    """The 2x2 shares the framing; only the payload length differs."""
    driver = GoCube2x2(FakeNus())
    states = []
    driver.connect("state", lambda _d, payload: states.append(payload))
    # GoCube reports faces in B F U D R L order with its own colour indices.
    order = [5, 2, 0, 3, 1, 4]
    colours = {5: 0, 2: 1, 0: 2, 3: 3, 1: 4, 4: 5}
    payload = bytes(colours[face] for face in order for _ in range(4))
    driver._on_data(_gocube_frame(gocube.MSG_STATE, payload))
    assert len(states) == 1
    from kubik.cube import Cube2
    assert Cube2.from_facelets(states[0]).is_solved()


def test_gocube_2x2_still_decodes_rotations():
    driver = GoCube2x2(FakeNus())
    seen = []
    driver.connect("move", lambda _d, face, q: seen.append((face, q)))
    driver._on_data(_gocube_frame(gocube.MSG_ROTATION, bytes([8])))
    assert seen == [("R", 1)]
