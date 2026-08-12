"""GAN Gen4, replayed against captures from a real cube.

Two sessions recorded from a GAN i Carry 4 over BlueZ and re-encrypted under a
synthetic MAC. The protocol was reverse engineered from these, so they are the
regression net for every table in `kubik.ble.gan`.
"""

import collections
import itertools
import pathlib

import pytest

from kubik.ble import gan
from kubik.ble.gan import GanGen4, _Encrypter
from test_ble import FakePeripheral


# --- GAN Gen4, against a real capture -----------------------------------------
# Recorded from a GAN i Carry 4 over BlueZ and re-encrypted under a synthetic
# MAC. Two passes of "each face four times": a botched R U F L D R', then a
# clean R U F D L B R'.

CAPTURE = pathlib.Path(__file__).parent / "data" / "gan_gen4_capture.txt"
FIXTURE_MAC = "AA:BB:CC:DD:EE:FF"


class FakeGen4(FakePeripheral):
    def __init__(self):
        super().__init__(FIXTURE_MAC)
        self.name = "GANic4_TEST"

    def uuids(self):
        return [GanGen4.notify_uuid, GanGen4.write_uuid]


def _replay(prime_after=8):
    driver = GanGen4(FakeGen4())
    moves, battery = [], []
    driver.connect("move",
                   lambda _d, f, q: moves.append(f + ("'" if q == 3 else "")))
    driver.connect("battery", lambda _d, b: battery.append(b))
    packets = [bytes.fromhex(line.strip())
               for line in CAPTURE.read_text().splitlines()
               if line and not line.startswith("#")]
    for i, packet in enumerate(packets):
        if i == prime_after:
            driver._primed = True
        driver._on_packet(packet)
    return moves, battery, len(packets)


def _runs(moves):
    return [(m, len(list(g))) for m, g in itertools.groupby(moves)]


def test_gen4_capture_decrypts_into_well_formed_records():
    """A wrong key would not produce a clean record walk over 445 packets."""
    crypto = _Encrypter(GanGen4.key_index, FIXTURE_MAC)
    kinds = collections.Counter()
    total = 0
    for line in CAPTURE.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        total += 1
        for kind, payload in gan.records(crypto.decrypt(bytes.fromhex(line))):
            kinds[kind] += 1
    assert total == 445
    # Every record type seen, with the lengths the protocol fixes for each.
    assert set(kinds) == {0x01, 0x02, 0x3A, 0xED, 0xEF}
    assert kinds[0xED] > kinds[0x01] > kinds[0x02]


def test_gen4_replays_the_recorded_session_exactly():
    moves, battery, packets = _replay()
    assert packets == 445
    assert battery == [99]
    fours = [m for m, n in _runs(moves) if n == 4]
    assert fours == ["R", "U", "F", "L", "D", "R'",
                     "R", "U", "F", "D", "L", "B", "R'"]


def test_gen4_ignores_the_connect_time_history_burst():
    """Unprimed, the driver must emit nothing at all."""
    driver = GanGen4(FakeGen4())
    moves = []
    driver.connect("move", lambda _d, f, q: moves.append(f))
    for line in CAPTURE.read_text().splitlines()[:20]:
        if line and not line.startswith("#"):
            driver._on_packet(bytes.fromhex(line))
    assert moves == []


def test_gen4_survives_duplicate_and_out_of_order_delivery():
    """Ordering is on the cube's clock, so replays and repeats are harmless."""
    straight, _, _ = _replay()
    driver = GanGen4(FakeGen4())
    moves = []
    driver.connect("move",
                   lambda _d, f, q: moves.append(f + ("'" if q == 3 else "")))
    packets = [bytes.fromhex(line.strip())
               for line in CAPTURE.read_text().splitlines()
               if line and not line.startswith("#")]
    for i, packet in enumerate(packets):
        if i == 8:
            driver._primed = True
        driver._on_packet(packet)
        driver._on_packet(packet)          # duplicate delivery
        if i > 20:
            driver._on_packet(packets[i - 5])   # a stale retransmission
    assert moves == straight


@pytest.mark.parametrize("code,expected", [
    (0x01, ("F", 1)), (0x02, ("B", 1)), (0x04, ("U", 1)),
    (0x08, ("D", 1)), (0x10, ("R", 1)), (0x20, ("L", 1)),
    (0x41, ("F", 3)), (0x50, ("R", 3)), (0x60, ("L", 3)),
])
def test_gen4_move_byte_is_one_hot_face_plus_a_direction_bit(code, expected):
    driver = GanGen4(FakeGen4())
    driver._primed = True
    seen = []
    driver.connect("move", lambda _d, f, q: seen.append((f, q)))
    driver._handle_move(bytes([0, 0, 0, 1, 0, 0, code]))
    assert seen == [expected]


def test_gen4_rejects_a_move_byte_naming_two_faces():
    driver = GanGen4(FakeGen4())
    driver._primed = True
    seen = []
    driver.connect("move", lambda _d, f, q: seen.append((f, q)))
    driver._handle_move(bytes([0, 0, 0, 1, 0, 0, 0x11]))
    assert seen == []


def test_gen4_uses_the_characteristics_the_hardware_advertises():
    """fff6 notifies and fff5 takes writes — the reverse of the assumption."""
    assert GanGen4.notify_uuid.startswith("0000fff6")
    assert GanGen4.write_uuid.startswith("0000fff5")
    assert GanGen4.key_index == 0
    assert GanGen4.implemented


def test_records_stops_cleanly_on_padding_and_overrun():
    assert list(gan.records(bytes(20))) == []                    # all padding
    assert list(gan.records(bytes([0x01, 0x11]) + bytes(18))) == []  # overruns
    assert list(gan.records(bytes([0xEF, 0x01, 0x63]) + bytes(17))) == \
        [(0xEF, b"\x63")]
    # A record followed by padding yields just the record.
    assert list(gan.records(bytes([0x01, 0x07]) + bytes(18))) == \
        [(0x01, bytes(7))]


# --- GAN Gen4 state decoding, against a full solved-to-solved session --------

SOLVE_CAPTURE = pathlib.Path(__file__).parent / "data" / "gan_gen4_solve.txt"


def _replay_capture(path, prime_after=8):
    from kubik.cube import Cube

    driver = GanGen4(FakeGen4())
    moves, states = [], []
    driver.connect("move",
                   lambda _d, f, q: moves.append(f + ("'" if q == 3 else "")))
    driver.connect("state", lambda _d, p: states.append(Cube(*p)))
    packets = [bytes.fromhex(line.strip())
               for line in path.read_text().splitlines()
               if line and not line.startswith("#")]
    for i, packet in enumerate(packets):
        if i == prime_after:
            driver._primed = True
        driver._on_packet(packet)
    return moves, states


def test_gen4_move_stream_returns_a_real_cube_to_solved():
    """254 turns recorded from a cube that started and finished solved."""
    from kubik.cube import Cube

    moves, _ = _replay_capture(SOLVE_CAPTURE)
    assert len(moves) == 254
    assert Cube().apply(moves).is_solved()


def test_gen4_decodes_every_reported_state_to_a_legal_cube():
    _, states = _replay_capture(SOLVE_CAPTURE)
    assert len(states) > 500
    for cube in states:
        cube.validate()          # raises if the permutation or parity is wrong


def test_gen4_state_agrees_with_the_move_stream():
    """The decisive test: the cube's own state reports and the moves it
    reported making must describe the same cube at every step."""
    from kubik.cube import Cube

    driver = GanGen4(FakeGen4())
    driver._primed = True
    model = Cube()
    seen = {"checked": 0, "pending": None}

    def on_move(_d, face, quarters):
        model.turn(face + ("'" if quarters == 3 else ""))
        seen["pending"] = model.copy()

    def on_state(_d, payload):
        if seen["pending"] is not None:
            assert Cube(*payload) == seen["pending"]
            seen["checked"] += 1

    driver.connect("move", on_move)
    driver.connect("state", on_state)
    packets = [bytes.fromhex(line.strip())
               for line in SOLVE_CAPTURE.read_text().splitlines()
               if line and not line.startswith("#")]
    for i, packet in enumerate(packets):
        if i < 8:
            continue          # the connect-time history burst
        driver._on_packet(packet)
    assert seen["checked"] > 200


def test_gen4_first_and_last_reported_state_are_solved():
    _, states = _replay_capture(SOLVE_CAPTURE)
    assert states[0].is_solved()
    assert states[-1].is_solved()


def test_gen4_state_decoding_works_on_the_other_session():
    """A different day, a different starting state, the same tables."""
    _, states = _replay_capture(CAPTURE)
    assert len(states) > 300
    for cube in states:
        cube.validate()


def test_scan_is_not_filtered_by_service_uuid():
    """A GAN i Carry 4 advertises no UUIDs, so a filtered scan never sees it."""
    import inspect

    from kubik.ble.bluez import Central

    source = inspect.getsource(Central.start_discovery)
    assert '"UUIDs"' not in source
