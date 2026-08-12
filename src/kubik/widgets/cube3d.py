"""A drag-rotatable cube, drawn with Cairo.

Cairo rather than GL: 54 quads with a painter's sort is nothing to rasterise,
and it removes GLArea/GLES from the dependency surface — which matters when the
same build has to run on a phone compositor.
"""

from __future__ import annotations

import math

from gi.repository import GObject, Gdk, Graphene, Gtk

from kubik.cube import COLOR_RGB, Cube

# Sticker geometry, parameterised on the number of cubies per edge so the same
# widget draws a 2x2 and a 3x3. For each face: the corner the grid starts from
# (in units of the half-extent) and the two in-plane unit vectors that walk
# along columns and rows, matching the net layout.
_FACE_BASIS = [
    ((-1, 1, -1), (1, 0, 0), (0, 0, 1)),     # U
    ((1, 1, 1), (0, 0, -1), (0, -1, 0)),     # R
    ((-1, 1, 1), (1, 0, 0), (0, -1, 0)),     # F
    ((-1, -1, 1), (1, 0, 0), (0, 0, -1)),    # D
    ((-1, 1, -1), (0, 0, 1), (0, -1, 0)),    # L
    ((1, 1, -1), (-1, 0, 0), (0, -1, 0)),    # B
]

_AXIS = {"U": (0, 1, 0), "D": (0, -1, 0), "R": (1, 0, 0),
         "L": (-1, 0, 0), "F": (0, 0, 1), "B": (0, 0, -1)}


def _sticker_quad(face: int, row: int, col: int, n: int, inset: float = 0.06):
    corner, u, v = _FACE_BASIS[face]
    half = n / 2
    origin = tuple(c * half for c in corner)
    points = []
    for du, dv in ((inset, inset), (1 - inset, inset),
                   (1 - inset, 1 - inset), (inset, 1 - inset)):
        points.append(tuple(
            origin[k] + u[k] * (col + du) + v[k] * (row + dv)
            for k in range(3)))
    return points


def _build_quads(n: int):
    quads = []
    for face in range(6):
        for row in range(n):
            for col in range(n):
                index = face * n * n + row * n + col
                quads.append((index, face,
                              _sticker_quad(face, row, col, n),
                              _sticker_quad(face, row, col, n, inset=0.0)))
    return quads


_QUAD_CACHE = {n: _build_quads(n) for n in (2, 3)}


def _rotate(point, axis, angle):
    if not angle:
        return point
    x, y, z = point
    ax, ay, az = axis
    norm = math.sqrt(ax * ax + ay * ay + az * az)
    ax, ay, az = ax / norm, ay / norm, az / norm
    c, s = math.cos(angle), math.sin(angle)
    dot = ax * x + ay * y + az * z
    return (
        x * c + (ay * z - az * y) * s + ax * dot * (1 - c),
        y * c + (az * x - ax * z) * s + ay * dot * (1 - c),
        z * c + (ax * y - ay * x) * s + az * dot * (1 - c),
    )


class CubeView(Gtk.Widget):
    """Renders a `Cube`, with drag-to-orbit and animated face turns."""

    __gtype_name__ = "KubikCubeView"

    yaw = GObject.Property(type=float, default=-0.62)
    pitch = GObject.Property(type=float, default=0.50)

    def __init__(self, cube=None):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._cube = cube if cube is not None else Cube()
        self._size = getattr(self._cube, "size", 3)
        self._facelets = self._cube.to_facelets()
        self._highlight: set[int] = set()
        self._dim = False
        self._anim = None
        self._tick = None

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        self.add_controller(drag)
        self._drag_origin = (self.yaw, self.pitch)

        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)
        self._zoom = 1.0

    # -- model -----------------------------------------------------------

    def set_cube(self, cube):
        self._cube = cube
        self._size = getattr(cube, "size", 3)
        self._facelets = cube.to_facelets()
        self.queue_draw()

    @property
    def size(self) -> int:
        return self._size

    def set_facelets(self, facelets):
        self._facelets = list(facelets)
        self.queue_draw()

    def set_highlight(self, indices, dim_others: bool = True):
        self._highlight = set(indices or ())
        self._dim = dim_others and bool(self._highlight)
        self.queue_draw()

    def animate(self, face: str, quarters: int, cube_after: Cube,
                duration: float = 0.18):
        """Spin one layer, then adopt the post-move state."""
        if face not in _AXIS:
            self.set_cube(cube_after)
            return
        if self.get_frame_clock() is None:
            # Not on screen yet, so no frame clock to drive the tween.
            self.set_cube(cube_after)
            return
        turns = 2 if quarters == 2 else 1
        direction = -1 if quarters == 3 else 1
        target = -direction * turns * math.pi / 2
        self._anim = {"face": face, "target": target, "progress": 0.0,
                      "after": cube_after,
                      "duration": duration * (2 if turns == 2 else 1)}
        if self._tick is None:
            self._start = None
            self._tick = self.add_tick_callback(self._on_tick)

    def is_animating(self) -> bool:
        return self._anim is not None

    def _on_tick(self, _widget, clock):
        anim = self._anim
        if anim is None:
            self._tick = None
            return GLib_SOURCE_REMOVE
        now = clock.get_frame_time() / 1e6
        if self._start is None:
            self._start = now
        t = min(1.0, (now - self._start) / anim["duration"])
        anim["progress"] = t * t * (3 - 2 * t)  # smoothstep
        self.queue_draw()
        if t >= 1.0:
            self.set_cube(anim["after"])
            self._anim = None
            self._start = None
            self._tick = None
            return GLib_SOURCE_REMOVE
        return GLib_SOURCE_CONTINUE

    # -- input -----------------------------------------------------------

    def _drag_begin(self, *_args):
        self._drag_origin = (self.yaw, self.pitch)

    def _drag_update(self, _gesture, dx, dy):
        yaw0, pitch0 = self._drag_origin
        self.yaw = yaw0 + dx * 0.008
        self.pitch = max(-1.4, min(1.4, pitch0 + dy * 0.008))
        self.queue_draw()

    def _on_scroll(self, _controller, _dx, dy):
        self._zoom = max(0.6, min(1.8, self._zoom - dy * 0.08))
        self.queue_draw()
        return True

    def reset_view(self):
        self.yaw, self.pitch, self._zoom = -0.62, 0.50, 1.0
        self.queue_draw()

    # -- drawing ----------------------------------------------------------

    def do_snapshot(self, snapshot):
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            return
        rect = Graphene.Rect().init(0, 0, width, height)
        ctx = snapshot.append_cairo(rect)
        self._draw(ctx, width, height)

    def _draw(self, ctx, width, height):
        n = self._size
        # Keep a 2x2 and a 3x3 the same apparent size on screen.
        scale = min(width, height) * (0.465 / n) * self._zoom
        cx, cy = width / 2, height / 2
        camera = 3.7 * n

        anim = self._anim
        spin_axis = spin_angle = None
        if anim is not None:
            spin_axis = _AXIS[anim["face"]]
            spin_angle = anim["target"] * anim["progress"]

        cos_y, sin_y = math.cos(self.yaw), math.sin(self.yaw)
        cos_p, sin_p = math.cos(self.pitch), math.sin(self.pitch)

        def transform(p):
            x, y, z = p
            x, z = x * cos_y + z * sin_y, -x * sin_y + z * cos_y
            y, z = y * cos_p - z * sin_p, y * sin_p + z * cos_p
            return x, y, z

        def project(p):
            x, y, z = p
            k = camera / (camera - z)
            return cx + x * scale * k, cy - y * scale * k

        faces = []
        layer_edge = n / 2 - 1
        for index, face, quad, backing in _QUAD_CACHE[n]:
            in_layer = False
            if spin_axis is not None:
                centroid = [sum(c[k] for c in quad) / 4 for k in range(3)]
                in_layer = sum(centroid[k] * spin_axis[k]
                               for k in range(3)) > layer_edge
            pts = quad
            back = backing
            if in_layer:
                pts = [_rotate(p, spin_axis, spin_angle) for p in pts]
                back = [_rotate(p, spin_axis, spin_angle) for p in back]
            view = [transform(p) for p in pts]
            back_view = [transform(p) for p in back]
            # Cull anything pointing away from the camera.
            (ax, ay, _), (bx, by, _), (dx_, dy_, _) = view[0], view[1], view[3]
            if (bx - ax) * (dy_ - ay) - (by - ay) * (dx_ - ax) > 0:
                continue
            depth = sum(p[2] for p in view) / 4
            faces.append((depth, index, face, view, back_view))

        faces.sort(key=lambda f: f[0])
        for _depth, index, face, view, back_view in faces:
            ctx.new_path()
            for i, p in enumerate(back_view):
                x, y = project(p)
                (ctx.move_to if i == 0 else ctx.line_to)(x, y)
            ctx.close_path()
            ctx.set_source_rgb(0.09, 0.09, 0.11)
            ctx.fill()

            r, g, b = COLOR_RGB[self._facelets[index]]
            if self._dim and index not in self._highlight:
                r, g, b = (0.45 + c * 0.22 for c in (r, g, b))
            ctx.new_path()
            for i, p in enumerate(view):
                x, y = project(p)
                (ctx.move_to if i == 0 else ctx.line_to)(x, y)
            ctx.close_path()
            ctx.set_source_rgb(r, g, b)
            ctx.fill_preserve()
            if index in self._highlight:
                ctx.set_source_rgb(1.0, 1.0, 1.0)
                ctx.set_line_width(max(2.0, scale * 0.07))
                ctx.stroke()
            else:
                ctx.new_path()


# Gtk.TickCallback wants the plain GLib constants; importing them by name keeps
# the tick handler readable.
GLib_SOURCE_CONTINUE = True
GLib_SOURCE_REMOVE = False


class NetView(Gtk.DrawingArea):
    """Flat unfolded net — used for lesson goals and algorithm recognition."""

    __gtype_name__ = "KubikNetView"

    def __init__(self, size: int = 3):
        super().__init__()
        self._size = size
        self._facelets = [i // (size * size) for i in range(6 * size * size)]
        self._mask = None
        self.set_content_width(220)
        self.set_content_height(170)
        self.set_draw_func(self._draw)

    @staticmethod
    def _layout(n):
        """Face origins in cell units: the usual cross-shaped net."""
        return {0: (n, 0), 1: (2 * n, n), 2: (n, n),
                3: (n, 2 * n), 4: (0, n), 5: (3 * n, n)}

    def set_size(self, size: int):
        if size != self._size:
            self._size = size
            self._facelets = [i // (size * size)
                              for i in range(6 * size * size)]
            self._mask = None
            self.queue_draw()

    def set_facelets(self, facelets):
        self._facelets = list(facelets)
        self._mask = None
        self.queue_draw()

    def set_mask(self, mask):
        """Show a lesson goal: -1 entries render as empty cells."""
        self._mask = list(mask) if mask else None
        self.queue_draw()

    def _draw(self, _area, ctx, width, height):
        n = self._size
        cell = min(width / (4 * n + 0.4), height / (3 * n + 0.4))
        ox = (width - cell * 4 * n) / 2
        oy = (height - cell * 3 * n) / 2
        source = self._mask if self._mask is not None else self._facelets
        layout = self._layout(n)
        for face in range(6):
            fx, fy = layout[face]
            for i in range(n * n):
                value = source[face * n * n + i]
                x = ox + (fx + i % n) * cell
                y = oy + (fy + i // n) * cell
                ctx.rectangle(x + 1, y + 1, cell - 2, cell - 2)
                if value is None or value < 0:
                    ctx.set_source_rgba(0.5, 0.5, 0.5, 0.16)
                else:
                    ctx.set_source_rgb(*COLOR_RGB[value])
                ctx.fill()
