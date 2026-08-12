"""Cubes: scanning, connecting, and what each family supports."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from kubik.ble.driver import drivers


class DevicesView(Gtk.Box):
    __gtype_name__ = "KubikDevicesView"

    def __init__(self, session):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session = session
        self._rows = {}

        self.banner = Adw.Banner(revealed=False)
        self.append(self.banner)

        self.connected_group = Adw.PreferencesGroup(title="Connected")
        self.connected_row = Adw.ActionRow(title="Nothing connected",
                                           subtitle="Using the on-screen cube")
        disconnect = Gtk.Button(label="Disconnect", valign=Gtk.Align.CENTER)
        disconnect.connect("clicked", lambda _b: session.disconnect_cube())
        self.disconnect_button = disconnect
        disconnect.set_visible(False)
        self.connected_row.add_suffix(disconnect)
        self.connected_group.add(self.connected_row)

        self.found_group = Adw.PreferencesGroup(
            title="Nearby cubes",
            description="Turn the cube once to wake its radio, then scan.")
        self.scan_button = Gtk.Button(label="Scan")
        self.scan_button.add_css_class("suggested-action")
        self.scan_button.connect("clicked", lambda _b: self._scan())
        self.found_group.set_header_suffix(self.scan_button)

        self.empty = Adw.ActionRow(title="No cubes found yet")
        self.found_group.add(self.empty)

        support = Adw.PreferencesGroup(
            title="Supported families",
            description="Every cube here reports its turns; the app tracks "
                        "state from those, seeded by a sync.")
        for cls in drivers():
            row = Adw.ActionRow(title=cls.label)
            if cls.implemented:
                row.set_subtitle("Moves"
                                 + (", absolute state" if cls.reports_state
                                    else ""))
                icon = Gtk.Image(icon_name="object-select-symbolic")
                icon.add_css_class("success")
            else:
                row.set_subtitle("Detected, protocol not decoded")
                icon = Gtk.Image(icon_name="dialog-warning-symbolic")
                icon.add_css_class("warning")
            row.add_suffix(icon)
            support.add(row)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_margin_top(18)
        body.set_margin_bottom(18)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.append(self.connected_group)
        body.append(self.found_group)
        body.append(support)

        scroller = Gtk.ScrolledWindow(
            hexpand=True, vexpand=True,
            child=Adw.Clamp(maximum_size=620, child=body))
        self.append(scroller)

        session.central.connect("device-added", self._on_added)
        session.central.connect("device-removed", self._on_removed)
        session.central.connect("scanning", self._on_scanning)
        session.central.connect("failed", self._on_failed)
        session.connect("status", self._on_status)
        session.connect("connection", lambda *_: self._refresh_connected())
        session.connect("notify::battery", lambda *_: self._refresh_connected())
        session.connect("notify::hardware",
                        lambda *_: self._refresh_connected())

    # -- scanning ------------------------------------------------------------

    def _scan(self):
        self.banner.set_revealed(False)
        if not self.session.start_scan():
            return
        GLib.timeout_add_seconds(20, self._auto_stop)

    def _auto_stop(self):
        self.session.stop_scan()
        return False

    def _on_scanning(self, _central, active):
        self.scan_button.set_label("Scanning…" if active else "Scan")
        self.scan_button.set_sensitive(not active)

    def _on_failed(self, _central, message):
        self.banner.set_title(message)
        self.banner.set_revealed(True)

    def _on_status(self, _session, message):
        self.banner.set_title(message)
        self.banner.set_revealed(True)

    def _on_added(self, _central, device):
        self.empty.set_visible(False)
        row = Adw.ActionRow(
            title=device.name or device.address,
            subtitle=f"{device.driver_label} · {device.address}"
                     + (f" · {device.rssi} dBm" if device.rssi else ""))
        button = Gtk.Button(label="Connect", valign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b, d=device: self._connect(d))
        row.add_suffix(button)
        self.found_group.add(row)
        self._rows[device.path] = row

    def _on_removed(self, _central, path):
        row = self._rows.pop(path, None)
        if row is not None:
            self.found_group.remove(row)
        if not self._rows:
            self.empty.set_visible(True)

    def _connect(self, device):
        self.banner.set_title(f"Connecting to {device.name or device.address}…")
        self.banner.set_revealed(True)
        self.session.connect_cube(device)

    # -- connected state -------------------------------------------------------

    def _refresh_connected(self):
        if self.session.connected:
            self.connected_row.set_title(self.session.device_name or "Cube")
            parts = []
            if self.session.battery >= 0:
                parts.append(f"Battery {self.session.battery}%")
            if self.session.hardware:
                parts.append(self.session.hardware)
            self.connected_row.set_subtitle(" · ".join(parts) or "Connected")
            self.disconnect_button.set_visible(True)
        else:
            self.connected_row.set_title("Nothing connected")
            self.connected_row.set_subtitle("Using the on-screen cube")
            self.disconnect_button.set_visible(False)
