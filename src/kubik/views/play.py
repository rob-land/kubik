"""Play: the cube itself, a move pad, and the solver."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from kubik.cube import random_scramble, random_scramble_2x2, tokenize
from kubik.solver import Unsolvable, solve, stage_title
from kubik.widgets.cube3d import CubeView

FACES = ["U", "D", "L", "R", "F", "B"]


class MovePad(Gtk.Box):
    """Twelve quarter turns, in a grid that reflows on a narrow screen."""

    __gtype_name__ = "KubikMovePad"

    def __init__(self, on_move):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("move-pad")
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                           max_children_per_line=6,
                           min_children_per_line=2,
                           homogeneous=True, row_spacing=6, column_spacing=6)
        for face in FACES:
            box = Gtk.Box(spacing=2)
            box.add_css_class("linked")
            for suffix in ("", "'"):
                button = Gtk.Button(label=face + suffix)
                button.add_css_class("move-button")
                button.connect("clicked",
                               lambda _b, m=face + suffix: on_move(m))
                box.append(button)
            grid.append(box)
        self.append(grid)


class PlayView(Gtk.Box):
    __gtype_name__ = "KubikPlayView"

    def __init__(self, session):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session = session
        self._queue: list[str] = []
        self._playing = False

        self.cube_view = CubeView(session.cube)
        self.cube_view.set_size_request(-1, 240)

        self.status = Gtk.Label(xalign=0.5, wrap=True)
        self.status.add_css_class("dim-label")
        self.status.set_text("Drag to turn the cube. Scroll to zoom.")

        pad = MovePad(self._on_pad)

        actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                              max_children_per_line=3,
                              min_children_per_line=1,
                              homogeneous=True, halign=Gtk.Align.CENTER,
                              row_spacing=6, column_spacing=6)
        for label, handler, css in (
                ("Scramble", self._scramble, "suggested-action"),
                ("Solve", self._solve, ""),
                ("Reset", self._reset, "")):
            button = Gtk.Button(label=label)
            button.add_css_class("pill")
            if css:
                button.add_css_class(css)
            button.connect("clicked", handler)
            actions.append(button)

        self.solution = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.solution.add_css_class("boxed-list")
        self.solution.set_visible(False)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(12)
        body.set_margin_bottom(12)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.append(self.cube_view)
        body.append(self.status)
        body.append(pad)
        body.append(actions)
        body.append(self.solution)

        clamp = Adw.Clamp(maximum_size=560, child=body)
        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True,
                                      child=clamp)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scroller)

        session.connect("moved", self._on_session_move)
        session.connect("changed", self._on_session_changed)

    # -- reacting to the session -----------------------------------------

    def _on_session_move(self, _session, move):
        face, rest = move[0], move[1:]
        quarters = 2 if rest == "2" else (3 if rest == "'" else 1)
        self.cube_view.animate(face, quarters, self.session.cube.copy())

    def _on_session_changed(self, _session):
        if not self.cube_view.is_animating():
            self.cube_view.set_cube(self.session.cube.copy())

    # -- actions -----------------------------------------------------------

    def _on_pad(self, move):
        self.session.apply_move(move)

    def _scramble(self, _button):
        self.solution.set_visible(False)
        self.session.reset()
        self.cube_view.set_cube(self.session.cube.copy())
        self._play(random_scramble_2x2(11) if self.session.size == 2
                   else random_scramble(22))
        self.status.set_text("Scrambled.")

    def on_puzzle_changed(self):
        self._queue.clear()
        self.solution.set_visible(False)
        self.cube_view.set_cube(self.session.cube.copy())
        self.status.set_text("Drag to turn the cube. Scroll to zoom.")

    def _reset(self, _button):
        self._queue.clear()
        self.solution.set_visible(False)
        self.session.reset()
        self.cube_view.set_cube(self.session.cube.copy())
        self.status.set_text("Back to solved.")

    def _solve(self, _button):
        while (child := self.solution.get_first_child()) is not None:
            self.solution.remove(child)
        try:
            steps = solve(self.session.cube)
        except Unsolvable as err:
            self.status.set_text(f"Could not solve this state ({err}).")
            return
        if not steps:
            self.status.set_text("Already solved.")
            self.solution.set_visible(False)
            return
        size = self.session.size
        total = sum(len(s.moves) for s in steps)
        self.status.set_text(f"{total} moves, layer by layer.")
        for step in steps:
            row = Adw.ActionRow(title=step.text,
                                subtitle=f"{stage_title(step.stage, size)}"
                                         f" — {step.label}")
            row.add_css_class("algorithm")
            button = Gtk.Button(icon_name="media-playback-start-symbolic",
                                valign=Gtk.Align.CENTER)
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, m=step.moves: self._play(m))
            row.add_suffix(button)
            self.solution.append(row)
        self.solution.set_visible(True)

    # -- playback -----------------------------------------------------------

    def _play(self, moves):
        self._queue.extend(tokenize(moves))
        if not self._playing:
            self._playing = True
            GLib.timeout_add(150, self._advance)

    def _advance(self):
        if not self._queue:
            self._playing = False
            return False
        self.session.apply_move(self._queue.pop(0))
        return True
