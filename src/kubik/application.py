"""Kubik — Adw.Application subclass."""

from __future__ import annotations

import logging

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from kubik.const import APP_ID, APP_NAME, VERSION
from kubik.window import KubikWindow

log = logging.getLogger(__name__)

_STYLE_RESOURCE = "/land/rob/kubik/ui/style.css"


class KubikApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._settings = Gio.Settings.new(APP_ID)

        # Registered so Gio.Application accepts and documents the flag;
        # configure_logging() reads sys.argv itself, well before this runs.
        self.add_main_option(
            "debug", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Enable debug logging", None,
        )

        self._make_action("about", self._show_about)
        self._make_action("quit", lambda *_: self.quit())

        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.show-help-overlay",
                                   ["<Control>question"])

    def _make_action(self, name: str, callback) -> Gio.SimpleAction:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        return action

    # -- lifecycle ---------------------------------------------------------

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_resource(_STYLE_RESOURCE)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            window = KubikWindow(application=self, settings=self._settings)
        window.present()

    def do_shutdown(self):
        window = self.props.active_window
        if window is not None:
            window.shutdown()
        Adw.Application.do_shutdown(self)

    # -- actions -----------------------------------------------------------

    def _show_about(self, *_args):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="rob",
            license_type=Gtk.License.GPL_3_0,
            comments=(
                "Learn to solve the Rubik's cube, with or without a smart "
                "cube."
            ),
            website="https://github.com/rob-land/kubik",
            issue_url="https://github.com/rob-land/kubik/issues",
        )
        about.present(self.props.active_window)
