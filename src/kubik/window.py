"""Kubik main window — the adaptive shell.

One `Adw.ViewStack` with five pages. Above 600sp the switcher sits in the
header bar; below it moves to a bottom bar, which is what makes the same
build usable on Phosh. Narrow is the default so the window sizes down to a
phone without the wide switcher pinning a minimum width on the header.

Single-pane by design: Kubik has no long-lived list alongside a detail view
of one selected thing, so `Adw.NavigationSplitView` would buy nothing. The
course does use an `Adw.NavigationView` internally to push a lesson, which is
a drill-down, not a split.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, Gio, GLib, Gtk

from kubik import curriculum
from kubik.ble.session import Session
from kubik.store import Store
from kubik.views.devices import DevicesView
from kubik.views.learn import LearnView
from kubik.views.play import PlayView
from kubik.views.solve import SolveView
from kubik.views.timer import TimerView

log = logging.getLogger(__name__)

PAGES = [
    ("learn", "Learn", "org.gnome.Settings-accessibility-symbolic"),
    ("play", "Play", "view-grid-symbolic"),
    ("solve", "Solve", "edit-find-symbolic"),
    ("timer", "Timer", "alarm-symbolic"),
    ("cubes", "Cubes", "bluetooth-symbolic"),
]


@Gtk.Template(resource_path="/land/rob/kubik/ui/window.ui")
class KubikWindow(Adw.ApplicationWindow):
    __gtype_name__ = "KubikWindow"

    toast_overlay:   Adw.ToastOverlay   = Gtk.Template.Child()
    header:          Adw.HeaderBar      = Gtk.Template.Child()
    window_title:    Adw.WindowTitle    = Gtk.Template.Child()
    view_stack:      Adw.ViewStack      = Gtk.Template.Child()
    switcher_bar:    Adw.ViewSwitcherBar = Gtk.Template.Child()
    wide_breakpoint: Adw.Breakpoint     = Gtk.Template.Child()

    def __init__(self, *, settings: Gio.Settings, **kwargs):
        super().__init__(**kwargs)
        self._settings = settings
        self.session = Session()
        self.store = Store()

        self.session.set_puzzle(settings.get_string("puzzle"))

        self._views = {
            "learn": LearnView(self.session, self.store),
            "play": PlayView(self.session),
            "solve": SolveView(self.session),
            "timer": TimerView(self.session, self.store),
            "cubes": DevicesView(self.session),
        }
        for name, title, icon in PAGES:
            page = self.view_stack.add_titled(self._views[name], name, title)
            page.set_icon_name(icon)
        self.view_stack.set_visible_child_name("learn")

        self.switcher = Adw.ViewSwitcher(
            stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)

        self._restore_geometry()
        self._install_actions()

        self.wide_breakpoint.connect("apply", self._on_wide, True)
        self.wide_breakpoint.connect("unapply", self._on_wide, False)
        self.view_stack.connect("notify::visible-child-name",
                                lambda *_: self._sync_title())
        self.session.connect("status", self._on_status)
        self.session.connect("notify::cube-type", self._on_puzzle_changed)
        self.connect("close-request", self._on_close_request)
        self._sync_title()

    # -- actions -----------------------------------------------------------

    def _install_actions(self):
        for name, callback in (("sync", self._sync),
                               ("reread", self._reread)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.puzzle_action = Gio.SimpleAction.new_stateful(
            "puzzle", GLib.VariantType("s"),
            GLib.Variant("s", self.session.cube_type))
        self.puzzle_action.connect("activate", self._on_puzzle_action)
        self.add_action(self.puzzle_action)

        help_action = Gio.SimpleAction.new("show-help-overlay", None)
        help_action.connect("activate", self._show_help_overlay)
        self.add_action(help_action)

    def _sync(self, *_args):
        self.session.reset()
        self.toast("Cube set to solved.")

    def _reread(self, *_args):
        if self.session.driver is None:
            self.toast("No cube connected.")
            return
        self.session.driver.request_state()
        self.toast("Asked the cube for its state.")

    def _show_help_overlay(self, *_args):
        builder = Gtk.Builder.new_from_resource(
            "/land/rob/kubik/ui/help-overlay.ui")
        overlay = builder.get_object("help_overlay")
        overlay.set_transient_for(self)
        overlay.present()

    # -- adaptive layout ---------------------------------------------------

    def _on_wide(self, _breakpoint, is_wide):
        self.header.set_title_widget(
            self.switcher if is_wide else self.window_title)
        self._sync_title()

    def _sync_title(self):
        page = self.view_stack.get_page(self.view_stack.get_visible_child())
        if page is not None:
            self.window_title.set_title(page.get_title() or "Kubik")
        label = dict(curriculum.PUZZLES).get(self.session.cube_type, "")
        self.window_title.set_subtitle(label)

    # -- puzzle selection --------------------------------------------------

    def _on_puzzle_action(self, _action, value):
        self.session.set_puzzle(value.get_string())

    def _on_puzzle_changed(self, *_args):
        cube_type = self.session.cube_type
        self.puzzle_action.set_state(GLib.Variant("s", cube_type))
        self._settings.set_string("puzzle", cube_type)
        self._sync_title()
        for view in self._views.values():
            if hasattr(view, "on_puzzle_changed"):
                view.on_puzzle_changed()
        log.info("switched to the %s", dict(curriculum.PUZZLES)[cube_type])
        self.toast(f"Switched to the {dict(curriculum.PUZZLES)[cube_type]}.")

    # -- geometry ----------------------------------------------------------

    def _restore_geometry(self):
        self.set_default_size(self._settings.get_int("window-width"),
                              self._settings.get_int("window-height"))
        if self._settings.get_boolean("window-maximized"):
            self.maximize()

    def _on_close_request(self, *_args):
        # get_width()/get_height(), not get_default_size(): the latter returns
        # the configured default, so a user resize would be discarded.
        if not self.is_maximized():
            self._settings.set_int("window-width", self.get_width())
            self._settings.set_int("window-height", self.get_height())
        self._settings.set_boolean("window-maximized", self.is_maximized())
        return False

    def shutdown(self):
        """Called from the application's do_shutdown."""
        self.session.disconnect_cube()

    # -- feedback ----------------------------------------------------------

    def _on_status(self, _session, message):
        self.toast(message)

    def toast(self, message: str):
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=3))
