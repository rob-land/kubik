"""BlueZ GATT client built on Gio's D-Bus stack.

Talking to org.bluez over D-Bus directly avoids pulling in a Bluetooth library
with its own event loop; everything here runs on the GLib main context the
rest of the app already uses.
"""

from __future__ import annotations

import logging
import time

from gi.repository import Gio, GLib, GObject

log = logging.getLogger(__name__)

BLUEZ = "org.bluez"
OM = "org.freedesktop.DBus.ObjectManager"
PROPS = "org.freedesktop.DBus.Properties"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
SERVICE = "org.bluez.GattService1"
CHARACTERISTIC = "org.bluez.GattCharacteristic1"

#: Every notification arrives twice, byte-identical and within a millisecond
#: — seen from both a GAN i Carry 4 and a Rubik's Connected X, so it is the
#: transport rather than any one cube. Genuine turns of the same face were
#: never closer than 149 ms even when scrambling quickly, so collapsing an
#: identical repeat inside this window cannot swallow a real move.
DUPLICATE_WINDOW = 0.025


def full_uuid(short: str) -> str:
    """Expand a 16-bit UUID to its 128-bit form; pass anything else through."""
    short = short.lower()
    if len(short) == 4:
        return f"0000{short}-0000-1000-8000-00805f9b34fb"
    return short


class BlueZError(Exception):
    pass


class Discovered(GObject.Object):
    """A device seen while scanning."""

    __gtype_name__ = "KubikDiscovered"

    path = GObject.Property(type=str, default="")
    address = GObject.Property(type=str, default="")
    name = GObject.Property(type=str, default="")
    rssi = GObject.Property(type=int, default=0)
    driver_id = GObject.Property(type=str, default="")
    driver_label = GObject.Property(type=str, default="")

    def __init__(self, path, address, name, rssi, uuids, manufacturer):
        super().__init__()
        self.path = path
        self.address = address or ""
        self.name = name or ""
        self.rssi = rssi or 0
        self.uuids = [u.lower() for u in (uuids or [])]
        self.manufacturer = manufacturer or {}


class Peripheral:
    """A connected device with its characteristics resolved."""

    def __init__(self, bus, path, address, name):
        self.bus = bus
        self.path = path
        self.address = address
        self.name = name
        self._chars: dict[str, tuple[str, list[str]]] = {}
        self._subs: dict[str, int] = {}
        self._on_disconnect = None

    # -- discovery of the GATT tree ------------------------------------

    def load_characteristics(self, objects):
        for obj_path, ifaces in objects.items():
            if not obj_path.startswith(self.path + "/"):
                continue
            char = ifaces.get(CHARACTERISTIC)
            if not char:
                continue
            uuid = str(char.get("UUID", "")).lower()
            flags = [str(f) for f in char.get("Flags", [])]
            self._chars[uuid] = (obj_path, flags)

    def has(self, uuid: str) -> bool:
        return full_uuid(uuid) in self._chars

    def uuids(self) -> list[str]:
        return list(self._chars)

    # -- I/O ------------------------------------------------------------

    def write(self, uuid: str, data: bytes, response: bool = False):
        uuid = full_uuid(uuid)
        entry = self._chars.get(uuid)
        if entry is None:
            raise BlueZError(f"characteristic {uuid} not present")
        path, flags = entry
        needs_response = response or "write-without-response" not in flags
        kind = "request" if needs_response else "command"
        # The a{sv} member is built from a plain dict of Variants. Wrapping it
        # in a Variant first makes GLib raise KeyError(0) while unpacking the
        # outer tuple, which surfaces as the deeply unhelpful message "0".
        body = GLib.Variant("(aya{sv})",
                            (list(data), {"type": GLib.Variant("s", kind)}))
        self.bus.call(BLUEZ, path, CHARACTERISTIC, "WriteValue", body,
                      None, Gio.DBusCallFlags.NONE, 5000, None,
                      self._log_result, f"write {uuid}")

    def subscribe(self, uuid: str, callback):
        """Enable notifications and route Value changes to `callback(bytes)`."""
        uuid = full_uuid(uuid)
        entry = self._chars.get(uuid)
        if entry is None:
            raise BlueZError(f"characteristic {uuid} not present")
        path, _ = entry
        last = {"value": None, "at": 0.0}

        def on_props(_conn, _sender, _path, _iface, _signal, params):
            iface, changed, _ = params.unpack()
            if iface != CHARACTERISTIC:
                return
            value = changed.get("Value")
            if value is None:
                return
            data = bytes(value)
            now = time.monotonic()
            if data == last["value"] and now - last["at"] < DUPLICATE_WINDOW:
                return
            last["value"], last["at"] = data, now
            callback(data)

        sub = self.bus.signal_subscribe(
            BLUEZ, PROPS, "PropertiesChanged", path, None,
            Gio.DBusSignalFlags.NONE, on_props)
        self._subs[uuid] = sub
        self.bus.call(BLUEZ, path, CHARACTERISTIC, "StartNotify", None,
                      None, Gio.DBusCallFlags.NONE, 5000, None,
                      self._log_result, f"notify {uuid}")

    def read(self, uuid: str, callback):
        uuid = full_uuid(uuid)
        entry = self._chars.get(uuid)
        if entry is None:
            callback(None)
            return
        path, _ = entry
        options = GLib.Variant("(a{sv})", ({},))

        def done(source, res, _):
            try:
                value = source.call_finish(res).unpack()[0]
            except GLib.Error as err:
                log.debug("read %s failed: %s", uuid, err.message)
                callback(None)
            else:
                callback(bytes(value))

        self.bus.call(BLUEZ, path, CHARACTERISTIC, "ReadValue", options,
                      None, Gio.DBusCallFlags.NONE, 5000, None, done, None)

    def disconnect(self):
        for uuid, sub in self._subs.items():
            self.bus.signal_unsubscribe(sub)
        self._subs.clear()
        self.bus.call(BLUEZ, self.path, DEVICE, "Disconnect", None, None,
                      Gio.DBusCallFlags.NONE, 5000, None,
                      self._log_result, "disconnect")

    @staticmethod
    def _log_result(source, res, what):
        try:
            source.call_finish(res)
        except GLib.Error as err:
            log.warning("%s: %s", what, err.message)


class Central(GObject.Object):
    """Scanning and connecting."""

    __gtype_name__ = "KubikCentral"

    __gsignals__ = {
        "device-added": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "device-removed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "scanning": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "failed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.bus: Gio.DBusConnection | None = None
        self.adapter: str | None = None
        self._seen: dict[str, Discovered] = {}
        self._filter = None
        self._watch = None
        self._scanning = False

    # -- lifecycle ------------------------------------------------------

    def start(self) -> bool:
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error as err:
            self.emit("failed", f"Cannot reach the system bus: {err.message}")
            return False
        objects = self._managed_objects()
        if objects is None:
            self.emit("failed", "BlueZ is not running.")
            return False
        for path, ifaces in objects.items():
            if ADAPTER in ifaces:
                self.adapter = path
                break
        if self.adapter is None:
            self.emit("failed", "No Bluetooth adapter found.")
            return False
        self._watch = self.bus.signal_subscribe(
            BLUEZ, OM, "InterfacesAdded", "/", None,
            Gio.DBusSignalFlags.NONE, self._on_interfaces_added)
        self.bus.signal_subscribe(
            BLUEZ, OM, "InterfacesRemoved", "/", None,
            Gio.DBusSignalFlags.NONE, self._on_interfaces_removed)
        self.bus.signal_subscribe(
            BLUEZ, PROPS, "PropertiesChanged", None, None,
            Gio.DBusSignalFlags.NONE, self._on_props_changed)
        return True

    def _managed_objects(self):
        try:
            reply = self.bus.call_sync(
                BLUEZ, "/", OM, "GetManagedObjects", None,
                GLib.VariantType("(a{oa{sa{sv}}})"),
                Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as err:
            log.warning("GetManagedObjects: %s", err.message)
            return None
        return reply.unpack()[0]

    def powered(self) -> bool:
        if not (self.bus and self.adapter):
            return False
        try:
            reply = self.bus.call_sync(
                BLUEZ, self.adapter, PROPS, "Get",
                GLib.Variant("(ss)", (ADAPTER, "Powered")),
                GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error:
            return False
        return bool(reply.unpack()[0])

    def set_powered(self, on: bool):
        if not (self.bus and self.adapter):
            return
        body = GLib.Variant("(ssv)",
                            (ADAPTER, "Powered", GLib.Variant("b", on)))
        self.bus.call(BLUEZ, self.adapter, PROPS, "Set", body, None,
                      Gio.DBusCallFlags.NONE, 5000, None,
                      Peripheral._log_result, "power on")

    # -- scanning -------------------------------------------------------

    def start_discovery(self, service_uuids=None):
        """Scan for cubes.

        Deliberately *not* filtered by service UUID. A GAN i Carry 4 advertises
        no UUIDs at all, so a filtered scan only ever turns up cubes BlueZ has
        already cached — a fresh machine would see nothing. Filtering happens in
        `identify()`, on the advertised name, which is what actually works.
        """
        if not (self.bus and self.adapter) or self._scanning:
            return
        options = {"Transport": GLib.Variant("s", "le"),
                   "DuplicateData": GLib.Variant("b", False)}
        self.bus.call(BLUEZ, self.adapter, ADAPTER, "SetDiscoveryFilter",
                      GLib.Variant("(a{sv})", (options,)), None,
                      Gio.DBusCallFlags.NONE, 5000, None,
                      self._filter_set, None)

    def _filter_set(self, source, res, _):
        try:
            source.call_finish(res)
        except GLib.Error as err:
            log.debug("SetDiscoveryFilter: %s", err.message)
        # Devices BlueZ already knows about never re-announce themselves.
        for path, ifaces in (self._managed_objects() or {}).items():
            if DEVICE in ifaces:
                self._add_device(path, ifaces[DEVICE])
        self.bus.call(BLUEZ, self.adapter, ADAPTER, "StartDiscovery", None,
                      None, Gio.DBusCallFlags.NONE, 5000, None,
                      self._discovery_started, None)

    def _discovery_started(self, source, res, _):
        try:
            source.call_finish(res)
        except GLib.Error as err:
            self.emit("failed", err.message)
            return
        self._scanning = True
        self.emit("scanning", True)

    def stop_discovery(self):
        if not (self.bus and self.adapter and self._scanning):
            return
        self._scanning = False
        self.emit("scanning", False)
        self.bus.call(BLUEZ, self.adapter, ADAPTER, "StopDiscovery", None,
                      None, Gio.DBusCallFlags.NONE, 5000, None,
                      Peripheral._log_result, "stop discovery")

    # -- device bookkeeping ---------------------------------------------

    def _add_device(self, path, props):
        from .driver import identify

        name = str(props.get("Alias") or props.get("Name") or "")
        uuids = [str(u) for u in props.get("UUIDs", [])]
        manufacturer = {int(k): bytes(v) for k, v
                        in dict(props.get("ManufacturerData", {})).items()}
        driver = identify(name, uuids)
        if driver is None:
            return
        device = Discovered(path, str(props.get("Address", "")), name,
                            int(props.get("RSSI", 0) or 0), uuids, manufacturer)
        device.driver_id = driver.id
        device.driver_label = driver.label
        known = self._seen.get(path)
        if known is not None:
            known.rssi = device.rssi
            return
        self._seen[path] = device
        self.emit("device-added", device)

    def _on_interfaces_added(self, _c, _s, _p, _i, _sig, params):
        path, ifaces = params.unpack()
        if DEVICE in ifaces:
            self._add_device(path, ifaces[DEVICE])

    def _on_interfaces_removed(self, _c, _s, _p, _i, _sig, params):
        path, _ = params.unpack()
        if self._seen.pop(path, None) is not None:
            self.emit("device-removed", path)

    def _on_props_changed(self, _c, _s, path, _i, _sig, params):
        iface, changed, _ = params.unpack()
        if iface != DEVICE:
            return
        if "RSSI" in changed and path in self._seen:
            self._seen[path].rssi = int(changed["RSSI"])

    # -- connecting -------------------------------------------------------

    def connect_device(self, device: Discovered, on_ready, on_error):
        """Connect, wait for the GATT tree, then hand back a Peripheral."""
        state = {"done": False, "tries": 0}

        def finish():
            if state["done"]:
                return True
            objects = self._managed_objects() or {}
            props = objects.get(device.path, {}).get(DEVICE, {})
            if not props.get("ServicesResolved"):
                state["tries"] += 1
                if state["tries"] > 60:
                    state["done"] = True
                    on_error("Timed out waiting for the cube's services.")
                    return False
                return True
            state["done"] = True
            peripheral = Peripheral(self.bus, device.path, device.address,
                                    device.name)
            peripheral.load_characteristics(objects)
            on_ready(peripheral)
            return False

        def connected(source, res, _):
            try:
                source.call_finish(res)
            except GLib.Error as err:
                state["done"] = True
                on_error(err.message)
                return
            GLib.timeout_add(250, finish)

        self.bus.call(BLUEZ, device.path, DEVICE, "Connect", None, None,
                      Gio.DBusCallFlags.NONE, 30000, None, connected, None)
