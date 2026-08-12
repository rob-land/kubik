"""Cube state, moves and notation.

Two representations are kept in sync-able form:

* the *cubie* level — corner/edge permutation and orientation — which is what
  moves act on and what the solver reasons about;
* the *facelet* level — 54 stickers in URFDLB order — which is what smart cubes
  report, what the renderer draws, and what the lesson masks are written
  against.

Facelet indices follow the usual convention::

             0  1  2
             3  4  5
             6  7  8
   36 37 38  18 19 20   9 10 11  45 46 47
   39 40 41  21 22 23  12 13 14  48 49 50
   42 43 44  24 25 26  15 16 17  51 52 53
            27 28 29
            30 31 32
            33 34 35

i.e. U = 0-8, R = 9-17, F = 18-26, D = 27-35, L = 36-44, B = 45-53.
"""

from __future__ import annotations

import random

# --- faces and colours ------------------------------------------------------

FACES = "URFDLB"
U, R, F, D, L, B = range(6)

#: A standard BOY cube held the way the course teaches it: white on the
#: bottom, yellow on top, blue in front. Putting the first layer on D and the
#: last layer on U is what lets every algorithm in the course be the textbook
#: one — `R U R' U'` really is R U R' U'.
COLOR_NAMES = ["yellow", "red", "blue", "white", "orange", "green"]

#: sRGB triples used by the renderer, in the same face order.
COLOR_RGB = [
    (0.98, 0.82, 0.14),  # U yellow
    (0.80, 0.16, 0.18),  # R red
    (0.12, 0.35, 0.72),  # F blue
    (0.96, 0.96, 0.94),  # D white
    (0.94, 0.49, 0.13),  # L orange
    (0.13, 0.62, 0.31),  # B green
]

# --- cubie naming -----------------------------------------------------------

CORNERS = ["URF", "UFL", "ULB", "UBR", "DFR", "DLF", "DBL", "DRB"]
EDGES = ["UR", "UF", "UL", "UB", "DR", "DF", "DL", "DB", "FR", "FL", "BL", "BR"]

CORNER_FACELET = [
    (8, 9, 20),    # URF
    (6, 18, 38),   # UFL
    (0, 36, 47),   # ULB
    (2, 45, 11),   # UBR
    (29, 26, 15),  # DFR
    (27, 44, 24),  # DLF
    (33, 53, 42),  # DBL
    (35, 17, 51),  # DRB
]

EDGE_FACELET = [
    (5, 10),   # UR
    (7, 19),   # UF
    (3, 37),   # UL
    (1, 46),   # UB
    (32, 16),  # DR
    (28, 25),  # DF
    (30, 43),  # DL
    (34, 52),  # DB
    (23, 12),  # FR
    (21, 41),  # FL
    (50, 39),  # BL
    (48, 14),  # BR
]

CORNER_COLOR = [
    (U, R, F), (U, F, L), (U, L, B), (U, B, R),
    (D, F, R), (D, L, F), (D, B, L), (D, R, B),
]

EDGE_COLOR = [
    (U, R), (U, F), (U, L), (U, B),
    (D, R), (D, F), (D, L), (D, B),
    (F, R), (F, L), (B, L), (B, R),
]

# --- quarter-turn definitions ----------------------------------------------
# (corner perm, corner twist, edge perm, edge flip) for each clockwise
# quarter turn, in Kociemba's formulation: entry i names the cubie that moves
# *into* slot i.

_QUARTER = {
    "U": ([3, 0, 1, 2, 4, 5, 6, 7], [0] * 8,
          [3, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11], [0] * 12),
    "R": ([4, 1, 2, 0, 7, 5, 6, 3], [2, 0, 0, 1, 1, 0, 0, 2],
          [8, 1, 2, 3, 11, 5, 6, 7, 4, 9, 10, 0], [0] * 12),
    "F": ([1, 5, 2, 3, 0, 4, 6, 7], [1, 2, 0, 0, 2, 1, 0, 0],
          [0, 9, 2, 3, 4, 8, 6, 7, 1, 5, 10, 11],
          [0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0]),
    "D": ([0, 1, 2, 3, 5, 6, 7, 4], [0] * 8,
          [0, 1, 2, 3, 5, 6, 7, 4, 8, 9, 10, 11], [0] * 12),
    "L": ([0, 2, 6, 3, 4, 1, 5, 7], [0, 1, 2, 0, 0, 2, 1, 0],
          [0, 1, 10, 3, 4, 5, 9, 7, 8, 2, 6, 11], [0] * 12),
    "B": ([0, 1, 3, 7, 4, 5, 2, 6], [0, 0, 1, 2, 0, 0, 2, 1],
          [0, 1, 2, 11, 4, 5, 6, 10, 8, 9, 3, 7],
          [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1]),
}


class Cube:
    """A 3x3x3 state at the cubie level."""

    __slots__ = ("cp", "co", "ep", "eo")

    def __init__(self, cp=None, co=None, ep=None, eo=None):
        self.cp = list(cp) if cp else list(range(8))
        self.co = list(co) if co else [0] * 8
        self.ep = list(ep) if ep else list(range(12))
        self.eo = list(eo) if eo else [0] * 12

    # -- basics --------------------------------------------------------

    def copy(self) -> "Cube":
        return Cube(self.cp, self.co, self.ep, self.eo)

    def __eq__(self, other):
        return (isinstance(other, Cube) and self.cp == other.cp
                and self.co == other.co and self.ep == other.ep
                and self.eo == other.eo)

    def __hash__(self):
        return hash((tuple(self.cp), tuple(self.co),
                     tuple(self.ep), tuple(self.eo)))

    def is_solved(self) -> bool:
        return (self.cp == list(range(8)) and self.co == [0] * 8
                and self.ep == list(range(12)) and self.eo == [0] * 12)

    # -- move application ----------------------------------------------

    def _multiply(self, cp, co, ep, eo):
        s_cp, s_co, s_ep, s_eo = self.cp, self.co, self.ep, self.eo
        self.cp = [s_cp[cp[i]] for i in range(8)]
        self.co = [(s_co[cp[i]] + co[i]) % 3 for i in range(8)]
        self.ep = [s_ep[ep[i]] for i in range(12)]
        self.eo = [(s_eo[ep[i]] + eo[i]) % 2 for i in range(12)]

    def turn(self, move: str) -> "Cube":
        """Apply one move in place and return self."""
        face, times = parse_move(move)
        defs = _QUARTER[face]
        for _ in range(times):
            self._multiply(*defs)
        return self

    def apply(self, seq) -> "Cube":
        """Apply a move sequence (string or iterable) in place."""
        for m in tokenize(seq):
            self.turn(m)
        return self

    def applied(self, seq) -> "Cube":
        return self.copy().apply(seq)

    # -- facelets ------------------------------------------------------

    def to_facelets(self) -> list[int]:
        f = [0] * 54
        for i in range(6):
            f[9 * i + 4] = i
        for slot in range(8):
            cubie = self.cp[slot]
            twist = self.co[slot]
            for k in range(3):
                f[CORNER_FACELET[slot][(k + twist) % 3]] = CORNER_COLOR[cubie][k]
        for slot in range(12):
            cubie = self.ep[slot]
            flip = self.eo[slot]
            for k in range(2):
                f[EDGE_FACELET[slot][(k + flip) % 2]] = EDGE_COLOR[cubie][k]
        return f

    @classmethod
    def from_facelets(cls, f) -> "Cube":
        """Rebuild a cubie state from 54 face indices.

        Raises ValueError if the stickers do not describe a real cube.
        """
        if len(f) != 54:
            raise ValueError("expected 54 facelets")
        cube = cls()
        for slot in range(8):
            cols = tuple(f[i] for i in CORNER_FACELET[slot])
            for cubie, home in enumerate(CORNER_COLOR):
                for twist in range(3):
                    if cols == tuple(home[(k - twist) % 3] for k in range(3)):
                        cube.cp[slot], cube.co[slot] = cubie, twist
                        break
                else:
                    continue
                break
            else:
                raise ValueError(f"corner {CORNERS[slot]} has no valid colours")
        for slot in range(12):
            cols = tuple(f[i] for i in EDGE_FACELET[slot])
            for cubie, home in enumerate(EDGE_COLOR):
                if cols == home:
                    cube.ep[slot], cube.eo[slot] = cubie, 0
                    break
                if cols == (home[1], home[0]):
                    cube.ep[slot], cube.eo[slot] = cubie, 1
                    break
            else:
                raise ValueError(f"edge {EDGES[slot]} has no valid colours")
        cube.validate()
        return cube

    def validate(self):
        if sorted(self.cp) != list(range(8)):
            raise ValueError("corners are not a permutation")
        if sorted(self.ep) != list(range(12)):
            raise ValueError("edges are not a permutation")
        if sum(self.co) % 3:
            raise ValueError("corner twist parity is wrong")
        if sum(self.eo) % 2:
            raise ValueError("edge flip parity is wrong")
        if _parity(self.cp) != _parity(self.ep):
            raise ValueError("permutation parity is wrong")

    # -- lookups used by the solver and the lessons --------------------

    def find_corner(self, cubie: int) -> tuple[int, int]:
        """Return (slot, twist) of a corner cubie."""
        slot = self.cp.index(cubie)
        return slot, self.co[slot]

    def find_edge(self, cubie: int) -> tuple[int, int]:
        """Return (slot, flip) of an edge cubie."""
        slot = self.ep.index(cubie)
        return slot, self.eo[slot]

    def matches(self, mask) -> bool:
        """Test a 54-entry lesson mask; -1 entries are wildcards."""
        f = self.to_facelets()
        return all(m < 0 or f[i] == m for i, m in enumerate(mask))


#: 2x2 sticker indices, in the same URFDLB face order with four per face.
#: Derived from the 3x3 table rather than retyped: a 2x2 is the corners of a
#: 3x3, so each corner sticker at (row, col) in {0, 2} maps to {0, 1}.
CORNER_FACELET_2 = [
    tuple((i // 9) * 4 + (0 if (i % 9) // 3 == 0 else 1) * 2
          + (0 if (i % 9) % 3 == 0 else 1) for i in group)
    for group in CORNER_FACELET
]


class Cube2:
    """A 2x2x2 state: eight corners and nothing else.

    A 2x2 has no centres, so "solved" is only meaningful relative to some
    frame. The frame here is the cube's own body — which is what a smart cube
    reports against, and what the on-screen cube displays — so whole-cube
    rotations simply do not arise, and no normalisation is needed.
    """

    __slots__ = ("cp", "co")

    size = 2

    def __init__(self, cp=None, co=None):
        self.cp = list(cp) if cp else list(range(8))
        self.co = list(co) if co else [0] * 8

    def copy(self) -> "Cube2":
        return Cube2(self.cp, self.co)

    def __eq__(self, other):
        return (isinstance(other, Cube2) and self.cp == other.cp
                and self.co == other.co)

    def __hash__(self):
        return hash((tuple(self.cp), tuple(self.co)))

    def is_solved(self) -> bool:
        return self.cp == list(range(8)) and self.co == [0] * 8

    def turn(self, move: str) -> "Cube2":
        face, times = parse_move(move)
        cp, co, _, _ = _QUARTER[face]
        for _ in range(times):
            s_cp, s_co = self.cp, self.co
            self.cp = [s_cp[cp[i]] for i in range(8)]
            self.co = [(s_co[cp[i]] + co[i]) % 3 for i in range(8)]
        return self

    def apply(self, seq) -> "Cube2":
        for m in tokenize(seq):
            self.turn(m)
        return self

    def applied(self, seq) -> "Cube2":
        return self.copy().apply(seq)

    def to_facelets(self) -> list[int]:
        f = [0] * 24
        for slot in range(8):
            cubie, twist = self.cp[slot], self.co[slot]
            for k in range(3):
                f[CORNER_FACELET_2[slot][(k + twist) % 3]] = \
                    CORNER_COLOR[cubie][k]
        return f

    @classmethod
    def from_facelets(cls, f) -> "Cube2":
        if len(f) != 24:
            raise ValueError("expected 24 facelets")
        cube = cls()
        for slot in range(8):
            cols = tuple(f[i] for i in CORNER_FACELET_2[slot])
            for cubie, home in enumerate(CORNER_COLOR):
                for twist in range(3):
                    if cols == tuple(home[(k - twist) % 3] for k in range(3)):
                        cube.cp[slot], cube.co[slot] = cubie, twist
                        break
                else:
                    continue
                break
            else:
                raise ValueError(f"corner {CORNERS[slot]} has no valid colours")
        cube.validate()
        return cube

    def validate(self):
        if sorted(self.cp) != list(range(8)):
            raise ValueError("corners are not a permutation")
        if sum(self.co) % 3:
            raise ValueError("corner twist parity is wrong")

    def find_corner(self, cubie: int) -> tuple[int, int]:
        slot = self.cp.index(cubie)
        return slot, self.co[slot]

    def matches(self, mask) -> bool:
        f = self.to_facelets()
        return all(m < 0 or f[i] == m for i, m in enumerate(mask))


#: A 3x3 also answers `size`, so widgets can render either without branching.
Cube.size = 3


def random_scramble_2x2(length: int = 11,
                        rng: random.Random | None = None) -> list[str]:
    """A 2x2 scramble.

    Only U, R and F: on a two-layer puzzle the opposite faces are the same
    turn seen from the other side, so the WCA notation for 2x2 leaves them out.
    """
    rng = rng or random
    moves: list[str] = []
    last = ""
    while len(moves) < length:
        face = rng.choice("URF")
        if face == last:
            continue
        moves.append(face + rng.choice(["", "'", "2"]))
        last = face
    return moves


def _parity(perm) -> int:
    p = 0
    for i in range(len(perm)):
        for j in range(i + 1, len(perm)):
            if perm[i] > perm[j]:
                p ^= 1
    return p


# --- notation ---------------------------------------------------------------

_SUFFIX = {"": 1, "'": 3, "2": 2, "’": 3, "‘": 3, "2'": 2}


def tokenize(seq) -> list[str]:
    """Split a sequence given as a string or an iterable into moves."""
    if seq is None:
        return []
    if not isinstance(seq, str):
        return [str(m) for m in seq]
    return [t for t in seq.replace("’", "'").replace("(", " ")
            .replace(")", " ").split() if t]


def parse_move(move: str) -> tuple[str, int]:
    """Return (face letter, number of clockwise quarter turns)."""
    move = move.strip().replace("’", "'")
    if not move or move[0] not in _QUARTER:
        raise ValueError(f"not a move: {move!r}")
    suffix = move[1:]
    if suffix not in _SUFFIX:
        raise ValueError(f"not a move: {move!r}")
    return move[0], _SUFFIX[suffix]


def format_move(face: str, times: int) -> str:
    times %= 4
    return "" if times == 0 else face + ("", "", "2", "'")[times]


def invert(seq) -> list[str]:
    out = []
    for m in reversed(tokenize(seq)):
        face, times = parse_move(m)
        out.append(format_move(face, -times % 4))
    return out


#: Faces in y-rotation order, used to re-express an algorithm for a different
#: front face without emitting whole-cube rotations.
_Y_CYCLE = "FRBL"


def rotate_alg(seq, quarters: int) -> list[str]:
    """Re-letter an algorithm as if the cube had been turned y `quarters` times."""
    quarters %= 4
    if quarters == 0:
        return tokenize(seq)
    out = []
    for m in tokenize(seq):
        face, times = parse_move(m)
        if face in _Y_CYCLE:
            face = _Y_CYCLE[(_Y_CYCLE.index(face) + quarters) % 4]
        out.append(format_move(face, times))
    return out


def cancel(seq) -> list[str]:
    """Collapse a move sequence: R R -> R2, R R' -> nothing, R2 R2 -> nothing.

    CubeStation runs the equivalent pass (`mergeRepetedFormula`) before showing
    solver output to a learner, and it makes a real difference to readability.
    """
    out: list[tuple[str, int]] = []
    for m in tokenize(seq):
        face, times = parse_move(m)
        if out and out[-1][0] == face:
            merged = (out.pop()[1] + times) % 4
            if merged:
                out.append((face, merged))
            continue
        # A move commutes past the opposite face, so R L R can also merge.
        if len(out) >= 2 and out[-2][0] == face and _opposite(out[-1][0], face):
            merged = (out[-2][1] + times) % 4
            keep = out.pop()
            out.pop()
            if merged:
                out.append((face, merged))
            out.append(keep)
            continue
        out.append((face, times))
    return [format_move(f, t) for f, t in out]


def _opposite(a: str, b: str) -> bool:
    return {a, b} in ({"U", "D"}, {"R", "L"}, {"F", "B"})


def random_scramble(length: int = 22, rng: random.Random | None = None) -> list[str]:
    """A random-move scramble with the usual redundancy filtering.

    Not WCA random-state, which needs an optimal solver; long enough that the
    difference does not matter for practice.
    """
    rng = rng or random
    moves: list[str] = []
    last = prev = ""
    while len(moves) < length:
        face = rng.choice(FACES)
        if face == last:
            continue
        if face == prev and _opposite(face, last):
            continue
        moves.append(face + rng.choice(["", "'", "2"]))
        prev, last = last, face
    return moves
