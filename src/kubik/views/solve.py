"""Solve: enter a cube's colours by hand, then get the moves.

The point of difference from the web solvers is that this one fills in what it
can work out. Paint four faces and the last two are mostly free; see
`kubik.facelets` for what makes that possible.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk

from kubik.cube import COLOR_NAMES, COLOR_RGB
from kubik.facelets import PartialCube
from kubik.solver import Unsolvable, solve, stage_title
from kubik.widgets.neteditor import NetEditor

log = logging.getLogger(__name__)


class SolveView(Gtk.Box):
    __gtype_name__ = "KubikSolveView"

    def __init__(self, session):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session = session
        self.partial = PartialCube()
        self._brush = 0

        self.editor = NetEditor(self.partial)
        self.editor.connect("sticker-clicked", self._on_sticker)

        self.status = Gtk.Label(xalign=0.5, wrap=True,
                                justify=Gtk.Justification.CENTER)
        self.status.add_css_class("dim-label")

        self.palette = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.palette.add_css_class("palette")
        self._swatches = {}
        for colour in range(6):
            button = Gtk.ToggleButton()
            button.set_child(_swatch(colour))
            button.set_tooltip_text(COLOR_NAMES[colour].capitalize())
            button.connect("toggled", self._on_brush, colour)
            self.palette.append(button)
            self._swatches[colour] = button
        self._swatches[0].set_active(True)

        self.eraser = Gtk.ToggleButton(icon_name="edit-clear-symbolic")
        self.eraser.set_tooltip_text("Erase")
        self.eraser.connect("toggled", self._on_brush, None)
        self.palette.append(self.eraser)

        actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                              max_children_per_line=3,
                              min_children_per_line=1, homogeneous=True,
                              halign=Gtk.Align.CENTER,
                              row_spacing=6, column_spacing=6)
        self.solve_button = Gtk.Button(label="Solve")
        self.solve_button.add_css_class("pill")
        self.solve_button.add_css_class("suggested-action")
        self.solve_button.set_sensitive(False)
        self.solve_button.connect("clicked", self._on_solve)
        actions.append(self.solve_button)

        for label, handler in (("Scan From Cube", self._on_from_cube),
                               ("Clear", self._on_clear)):
            button = Gtk.Button(label=label)
            button.add_css_class("pill")
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
        body.append(_hint("Pick a colour, then tap the stickers. A ring marks "
                          "a sticker worked out from the ones you entered."))
        body.append(self.palette)
        body.append(self.editor)
        body.append(self.status)
        body.append(actions)
        body.append(self.solution)

        scroller = Gtk.ScrolledWindow(
            hexpand=True, vexpand=True,
            child=Adw.Clamp(maximum_size=560, child=body))
        self.append(scroller)
        self._refresh()

    # -- painting ----------------------------------------------------------

    def _on_brush(self, button, colour):
        if not button.get_active():
            return
        self._brush = colour
        for other_colour, swatch in self._swatches.items():
            if other_colour != colour:
                swatch.set_active(False)
        if colour is not None:
            self.eraser.set_active(False)

    def _on_sticker(self, _editor, index):
        self.partial.set(index, self._brush)
        self._refresh()

    def _on_clear(self, _button):
        self.partial.clear()
        self.solution.set_visible(False)
        self._refresh()

    def _on_from_cube(self, _button):
        """Seed from the cube the app already believes in."""
        facelets = self.session.cube.to_facelets()
        if len(facelets) != 54:
            self.status.set_text("Switch to the 3×3 to use this.")
            return
        self.partial.clear()
        for index, colour in enumerate(facelets):
            self.partial.set(index, colour)
        self._refresh()

    def _refresh(self):
        self.editor.refresh()
        ready, message = self.partial.status()
        self.status.set_text(message)
        self.status.remove_css_class("error")
        if self.partial.problem:
            self.status.add_css_class("error")
        self.solve_button.set_sensitive(ready)
        for colour, swatch in self._swatches.items():
            left = self.partial.remaining(colour)
            swatch.set_tooltip_text(
                f"{COLOR_NAMES[colour].capitalize()} — {left} left")
            swatch.set_sensitive(left > 0 or self._brush == colour)

    # -- solving -----------------------------------------------------------

    def _on_solve(self, _button):
        while (child := self.solution.get_first_child()) is not None:
            self.solution.remove(child)
        try:
            cube = self.partial.to_cube()
            steps = solve(cube)
        except (ValueError, Unsolvable) as err:
            self.status.set_text(f"Could not solve that: {err}.")
            self.status.add_css_class("error")
            return
        if not steps:
            self.status.set_text("That cube is already solved.")
            self.solution.set_visible(False)
            return
        total = sum(len(step.moves) for step in steps)
        self.status.set_text(f"{total} moves, layer by layer.")
        for step in steps:
            row = Adw.ActionRow(
                title=step.text,
                subtitle=f"{stage_title(step.stage, 3)} — {step.label}")
            row.add_css_class("algorithm")
            self.solution.append(row)
        self.solution.set_visible(True)
        # Hand the state to the rest of the app so Play can walk through it.
        self.session.reset(cube)
        log.info("solved a hand-entered cube in %d moves", total)


def _swatch(colour: int) -> Gtk.DrawingArea:
    area = Gtk.DrawingArea()
    area.set_content_width(30)
    area.set_content_height(30)

    def draw(_area, ctx, width, height):
        ctx.arc(width / 2, height / 2, min(width, height) / 2 - 2, 0, 6.2832)
        ctx.set_source_rgb(*COLOR_RGB[colour])
        ctx.fill_preserve()
        ctx.set_source_rgba(0, 0, 0, 0.4)
        ctx.set_line_width(1.5)
        ctx.stroke()

    area.set_draw_func(draw)
    return area


def _hint(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0.5, wrap=True,
                      justify=Gtk.Justification.CENTER)
    label.add_css_class("dim-label")
    return label
