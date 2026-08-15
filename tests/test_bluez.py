"""The BlueZ transport, exercised without a radio.

Every D-Bus payload this module builds is checked here. That sounds
over-careful until you have shipped `GLib.Variant("(aya{sv})", (data,
already_a_variant))`, which raises `KeyError(0)` — a message that reaches the
user as "Could not start the cube: 0" and points nowhere near the cause.
Notifications kept working throughout, because reading needs no payload, so
nothing else caught it.
"""

from __future__ import annotations

import pytest

from gi.repository import GLib

from kubik.ble.bluez import CHARACTERISTIC, Peripheral, full_uuid

WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"


class FakeBus:
    """Records Gio.DBusConnection calls instead of making them."""

    def __init__(self):
        self.calls = []
        self.subscriptions = 0

    def call(self, dest, path, iface, method, body, reply_type, flags,
             timeout, cancellable, callback, user_data):
        self.calls.append({"path": path, "interface": iface,
                           "method": method, "body": body})

    def call_sync(self, *args, **kwargs):
        raise AssertionError("the transport should not block the main loop")

    def signal_subscribe(self, *args):
        self.subscriptions += 1
        self.handler = args[-1]
        return self.subscriptions

    def deliver(self, value: bytes):
        """Fire a PropertiesChanged carrying a characteristic Value."""
        params = GLib.Variant(
            "(sa{sv}as)",
            (CHARACTERISTIC, {"Value": GLib.Variant("ay", list(value))}, []))
        self.handler(None, None, "/path", None, "PropertiesChanged", params)

    def signal_unsubscribe(self, _id):
        pass


@pytest.fixture
def peripheral():
    bus = FakeBus()
    device = Peripheral(bus, "/org/bluez/hci0/dev_X", "AA:BB:CC:DD:EE:FF",
                        "RubiksX")
    device._chars = {
        full_uuid(WRITE_UUID): ("/org/bluez/hci0/dev_X/service/char0",
                                ["write-without-response", "write"]),
        full_uuid("2a19"): ("/org/bluez/hci0/dev_X/service/char1", ["read"]),
    }
    return device


def test_uuid_expansion():
    assert full_uuid("fff5") == "0000fff5-0000-1000-8000-00805f9b34fb"
    assert full_uuid(WRITE_UUID.upper()) == WRITE_UUID


def test_write_builds_a_payload_dbus_accepts(peripheral):
    """The regression: this used to raise KeyError(0) before reaching D-Bus."""
    peripheral.write(WRITE_UUID, b"\x33")
    assert len(peripheral.bus.calls) == 1
    call = peripheral.bus.calls[0]
    assert call["method"] == "WriteValue"
    assert call["interface"] == CHARACTERISTIC
    assert call["body"].get_type_string() == "(aya{sv})"
    data, options = call["body"].unpack()
    assert bytes(data) == b"\x33"
    assert options == {"type": "command"}


def test_write_uses_command_for_write_without_response(peripheral):
    peripheral.write(WRITE_UUID, b"\x01")
    assert peripheral.bus.calls[0]["body"].unpack()[1]["type"] == "command"


def test_write_asks_for_a_response_when_required(peripheral):
    peripheral._chars[full_uuid(WRITE_UUID)] = ("/path", ["write"])
    peripheral.write(WRITE_UUID, b"\x01")
    assert peripheral.bus.calls[0]["body"].unpack()[1]["type"] == "request"

    peripheral.bus.calls.clear()
    peripheral._chars[full_uuid(WRITE_UUID)] = (
        "/path", ["write-without-response"])
    peripheral.write(WRITE_UUID, b"\x01", response=True)
    assert peripheral.bus.calls[0]["body"].unpack()[1]["type"] == "request"


def test_write_to_a_missing_characteristic_says_which(peripheral):
    from kubik.ble.bluez import BlueZError

    with pytest.raises(BlueZError) as excinfo:
        peripheral.write("0000dead-0000-1000-8000-00805f9b34fb", b"\x01")
    assert "dead" in str(excinfo.value)


def test_subscribe_registers_and_enables_notifications(peripheral):
    seen = []
    peripheral.subscribe(WRITE_UUID, seen.append)
    assert peripheral.bus.subscriptions == 1
    assert peripheral.bus.calls[0]["method"] == "StartNotify"


def test_every_driver_can_issue_its_requests():
    """Each driver's request_state must survive the real write path.

    This is the check that was missing: the drivers were only ever tested
    against fakes with their own write, so a broken transport went unnoticed.
    """
    from kubik.ble.gan import GanGen2, GanGen4
    from kubik.ble.gocube import GoCube

    for cls in (GanGen2, GanGen4, GoCube):
        bus = FakeBus()
        device = Peripheral(bus, "/org/bluez/hci0/dev_X",
                            "AA:BB:CC:DD:EE:FF", "cube")
        device._chars = {
            full_uuid(cls.write_uuid): ("/path", ["write-without-response"]),
            full_uuid(cls.notify_uuid): ("/path2", ["notify"]),
        }
        driver = cls(device)
        driver.request_state()
        for call in bus.calls:
            assert call["body"].get_type_string() == "(aya{sv})"
            data, options = call["body"].unpack()
            assert len(data) >= 1
            assert options["type"] in ("command", "request")


# --- duplicate notifications --------------------------------------------------
# Every notification arrives twice, byte-identical, within a millisecond. Seen
# from a GAN i Carry 4 and a Rubik's Connected X alike, so it is collapsed once
# in the transport rather than in each driver.

def test_identical_notifications_within_the_window_collapse(peripheral):
    seen = []
    peripheral.subscribe(WRITE_UUID, seen.append)
    peripheral.bus.deliver(b"\x2a\x06\x01\x08\x03\x3c\x0d\x0a")
    peripheral.bus.deliver(b"\x2a\x06\x01\x08\x03\x3c\x0d\x0a")
    assert len(seen) == 1


def test_different_notifications_are_both_delivered(peripheral):
    seen = []
    peripheral.subscribe(WRITE_UUID, seen.append)
    peripheral.bus.deliver(b"\x01")
    peripheral.bus.deliver(b"\x02")
    assert len(seen) == 2


def test_a_genuine_repeat_after_the_window_still_arrives(peripheral, monkeypatch):
    """Turning the same face twice must not be swallowed."""
    import kubik.ble.bluez as bluez

    clock = {"now": 1000.0}
    monkeypatch.setattr(bluez.time, "monotonic", lambda: clock["now"])
    seen = []
    peripheral.subscribe(WRITE_UUID, seen.append)
    peripheral.bus.deliver(b"\x08")
    clock["now"] += 0.001            # the duplicate
    peripheral.bus.deliver(b"\x08")
    clock["now"] += 0.149            # the closest genuine repeat ever observed
    peripheral.bus.deliver(b"\x08")
    assert len(seen) == 2


def test_the_window_sits_well_clear_of_both_extremes():
    """1 ms duplicates, 149 ms genuine repeats — leave room on both sides."""
    from kubik.ble.bluez import DUPLICATE_WINDOW

    assert 0.005 < DUPLICATE_WINDOW < 0.100
