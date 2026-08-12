"""Timer: scramble, inspection, solve, statistics.

With a cube connected the timer runs itself — it starts on the first turn after
the scramble and stops the instant the cube reads solved, which is the one
thing a smart cube does that a stopwatch cannot.
"""

from __future__ import annotations

import time

from gi.repository import Adw, GLib, Gdk, Gtk

from kubik.cube import Cube, Cube2, random_scramble, random_scramble_2x2
from kubik.store import format_time

IDLE, INSPECTING, RUNNING = range(3)


class TimerView(Gtk.Box):
    __gtype_name__ = "KubikTimerView"

    def __init__(self, session, store):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session = session
        self.store = store
        self.state = IDLE
        self.started = 0.0
        self.inspection_end = 0.0
        self.scramble: list[str] = []
        self.moves = 0
        self._tick = None

        self.scramble_label = Gtk.Label(xalign=0.5, wrap=True,
                                        justify=Gtk.Justification.CENTER)
        self.scramble_label.add_css_class("scramble")

        self.display = Gtk.Label(label="0.000", xalign=0.5)
        self.display.add_css_class("timer-display")

        self.hint = Gtk.Label(xalign=0.5, wrap=True)
        self.hint.add_css_class("dim-label")

        self.primary = Gtk.Button(label="Start")
        self.primary.add_css_class("pill")
        self.primary.add_css_class("suggested-action")
        self.primary.connect("clicked", lambda _b: self._primary())

        new_scramble = Gtk.Button(label="New scramble")
        new_scramble.add_css_class("pill")
        new_scramble.connect("clicked", lambda _b: self.new_scramble())

        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        buttons.append(self.primary)
        buttons.append(new_scramble)

        self.stats = Adw.PreferencesGroup(title="Statistics")
        self.stat_rows = {}
        for key, title in (("best", "Best"), ("ao5", "Average of 5"),
                           ("ao12", "Average of 12"), ("count", "Solves")):
            row = Adw.ActionRow(title=title)
            value = Gtk.Label(label="—")
            value.add_css_class("numeric")
            row.add_suffix(value)
            self.stat_rows[key] = value
            self.stats.add(row)

        self.history = Adw.PreferencesGroup(title="Recent solves")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.set_margin_top(18)
        body.set_margin_bottom(18)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.append(self.scramble_label)
        body.append(self.display)
        body.append(self.hint)
        body.append(buttons)
        body.append(self.stats)
        body.append(self.history)

        scroller = Gtk.ScrolledWindow(
            hexpand=True, vexpand=True,
            child=Adw.Clamp(maximum_size=560, child=body))
        self.append(scroller)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)
        self.set_focusable(True)

        session.connect("moved", self._on_move)
        session.connect("connection", lambda *_: self._update_hint())
        self.new_scramble()
        self.refresh()

    # -- scrambling ---------------------------------------------------------

    def new_scramble(self):
        two = self.session.size == 2
        self.scramble = random_scramble_2x2(11) if two else random_scramble(22)
        self.scramble_label.set_text(" ".join(self.scramble))
        self.target = (Cube2() if two else Cube()).apply(self.scramble)
        self.armed = False
        self._reset_display()
        self._update_hint()

    def _update_hint(self):
        if not self.session.connected:
            self.hint.set_text(
                "Press Start, or hit space. Connect a smart cube and the "
                "timer runs itself.")
        elif self.armed:
            self.hint.set_text("Ready — the timer starts on your next turn.")
        else:
            self.hint.set_text(
                "Apply the scramble to your cube. The timer arms itself once "
                "the cube matches, starts on your next turn, and stops the "
                "moment it reads solved.")

    def _reset_display(self):
        self.display.set_text("0.000")
        self.display.remove_css_class("inspecting")
        self.state = IDLE
        self.primary.set_label("Start")
        self.moves = 0

    # -- running --------------------------------------------------------------

    def _primary(self):
        if self.state == RUNNING:
            self._stop()
        else:
            self._start()

    def _start(self):
        self.state = RUNNING
        self.started = time.monotonic()
        self.moves = 0
        self.primary.set_label("Stop")
        self.display.remove_css_class("inspecting")
        if self._tick is None:
            self._tick = GLib.timeout_add(16, self._on_tick)

    def _stop(self):
        if self.state != RUNNING:
            return
        millis = int((time.monotonic() - self.started) * 1000)
        self.state = IDLE
        self.primary.set_label("Start")
        if self._tick is not None:
            GLib.source_remove(self._tick)
            self._tick = None
        self.display.set_text(format_time(millis / 1000))
        self.store.add_solve(millis, " ".join(self.scramble), self.moves,
                             self.session.cube_type)
        self.refresh()
        self.new_scramble()
        self.display.set_text(format_time(millis / 1000))

    def _on_tick(self):
        if self.state != RUNNING:
            self._tick = None
            return False
        self.display.set_text(format_time(time.monotonic() - self.started))
        return True

    def _on_key(self, _controller, keyval, _code, _mods):
        if keyval in (Gdk.KEY_space, Gdk.KEY_Return):
            self._primary()
            return True
        return False

    def _on_move(self, _session, _move):
        """Arm on the scramble, start on the first solving turn, stop on solved."""
        if not self.session.connected:
            return
        if self.state == RUNNING:
            self.moves += 1
            if self.session.cube.is_solved():
                self._stop()
            return
        if not self.armed:
            if self.session.cube == self.target:
                self.armed = True
                self._update_hint()
            return
        self._start()
        self.moves = 1

    # -- statistics -----------------------------------------------------------

    def on_puzzle_changed(self):
        self.new_scramble()
        self.refresh()

    def refresh(self):
        puzzle = self.session.cube_type
        best = self.store.best(puzzle)
        self.stat_rows["best"].set_text(
            format_time(best) if best is not None else "—")
        for key, n in (("ao5", 5), ("ao12", 12)):
            value = self.store.average_of(n, puzzle)
            self.stat_rows[key].set_text(
                format_time(value) if value is not None else "—")
        self.stat_rows["count"].set_text(str(self.store.count(puzzle)))

        self._rebuild_history()

    def _rebuild_history(self):
        for row in getattr(self, "_history_rows", []):
            self.history.remove(row)
        self._history_rows = []
        for solve in self.store.recent(12, self.session.cube_type):
            row = Adw.ActionRow(title=format_time(solve.effective),
                                subtitle=solve.scramble or "—")
            row.add_css_class("numeric")
            box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
            for label, penalty in (("+2", "+2"), ("DNF", "dnf"),
                                   ("OK", "")):
                button = Gtk.Button(label=label)
                button.add_css_class("flat")
                button.connect(
                    "clicked",
                    lambda _b, i=solve.id, p=penalty: self._penalise(i, p))
                box.append(button)
            delete = Gtk.Button(icon_name="user-trash-symbolic")
            delete.add_css_class("flat")
            delete.connect("clicked",
                           lambda _b, i=solve.id: self._delete(i))
            box.append(delete)
            row.add_suffix(box)
            self.history.add(row)
            self._history_rows.append(row)

    def _penalise(self, solve_id, penalty):
        self.store.set_penalty(solve_id, penalty)
        self.refresh()

    def _delete(self, solve_id):
        self.store.delete_solve(solve_id)
        self.refresh()
