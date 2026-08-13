"""A paintable unfolded net.

Draws the same cross-shaped layout as `NetView` but takes taps, and
distinguishes three kinds of cell: what you painted, what the app worked out
from what you painted, and what is still unknown. The distinction matters —
if the app fills in a third of the cube for you, you need to be able to see
which third, and correct it.
"""

from __future__ import annotations

from gi.repository import GObject, Gtk

from kubik.cube import COLOR_RGB

#: Face origins in cell units, cross-shaped: U on top, D below, L F R B across.
LAYOUT = {0: (3, 0), 1: (6, 3), 2: (3, 3), 3: (3, 6), 4: (0, 3), 5: (9, 3)}
COLUMNS = 12
ROWS = 9


def cell_geometry(width: float, height: float):
    """Cell size and origin for a net drawn into this allocation."""
    cell = min(width / (COLUMNS + 0.4), height / (ROWS + 0.4))
    return cell, (width - cell * COLUMNS) / 2, (height - cell * ROWS) / 2


def cell_rect(index: int, cell: float, ox: float, oy: float):
    face, offset = divmod(index, 9)
    fx, fy = LAYOUT[face]
    return (ox + (fx + offset % 3) * cell, oy + (fy + offset // 3) * cell,
            cell, cell)


class NetEditor(Gtk.DrawingArea):
    """Renders a `PartialCube` and reports taps on its cells."""

    __gtype_name__ = "KubikNetEditor"

    __gsignals__ = {
        "sticker-clicked": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, partial):
        super().__init__()
        self.partial = partial
        self.set_content_width(300)
        self.set_content_height(230)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

    def refresh(self):
        self.queue_draw()

    # -- input -------------------------------------------------------------

    def _on_pressed(self, _gesture, _n_press, x, y):
        cell, ox, oy = cell_geometry(self.get_width(), self.get_height())
        if cell <= 0:
            return
        for index in range(54):
            cx, cy, w, h = cell_rect(index, cell, ox, oy)
            if cx <= x < cx + w and cy <= y < cy + h:
                self.emit("sticker-clicked", index)
                return

    # -- drawing -----------------------------------------------------------

    def _draw(self, _area, ctx, width, height):
        cell, ox, oy = cell_geometry(width, height)
        for index in range(54):
            x, y, w, h = cell_rect(index, cell, ox, oy)
            value = self.partial.facelets[index]
            inset = max(1.0, cell * 0.06)
            ctx.rectangle(x + inset, y + inset,
                          w - 2 * inset, h - 2 * inset)
            if value is None:
                ctx.set_source_rgba(0.5, 0.5, 0.5, 0.16)
                ctx.fill()
                continue
            ctx.set_source_rgb(*COLOR_RGB[value])
            ctx.fill_preserve()
            ctx.set_source_rgba(0, 0, 0, 0.35)
            ctx.set_line_width(max(1.0, cell * 0.04))
            ctx.stroke()

            if index in self.partial.deduced:
                # A hollow ring marks a sticker the app inferred rather than
                # one that was painted.
                ctx.arc(x + w / 2, y + h / 2, cell * 0.16, 0, 6.2832)
                ctx.set_source_rgba(0, 0, 0, 0.45)
                ctx.set_line_width(max(1.0, cell * 0.06))
                ctx.stroke()
