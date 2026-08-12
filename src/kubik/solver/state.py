"""The packed cube state the solver works on.

A state is a plain `(cp, co, ep, eo)` tuple of tuples: cheap to copy,
hashable, and fast enough that the cross search can walk hundreds of
thousands of nodes without noticing. Moves are precomputed for all
eighteen face turns rather than composed from quarter turns each time."""

from __future__ import annotations

from dataclasses import dataclass, field

from kubik.cube import format_move, tokenize, _QUARTER

#: Cubie slots by layer, in the D-first frame.
FIRST_EDGES = (4, 5, 6, 7)
FIRST_CORNERS = (4, 5, 6, 7)
MIDDLE_EDGES = (8, 9, 10, 11)
LAST_EDGES = (0, 1, 2, 3)
LAST_CORNERS = (0, 1, 2, 3)


@dataclass
class Step:
    """One explicable chunk of a solution."""

    stage: str
    label: str
    moves: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.moves)


class Unsolvable(Exception):
    pass


# --- precomputed full moves -------------------------------------------------

ALL_MOVES = [f + s for f in "URFDLB" for s in ("", "'", "2")]


def _compose(a, b):
    cp = [a[0][b[0][i]] for i in range(8)]
    co = [(a[1][b[0][i]] + b[1][i]) % 3 for i in range(8)]
    ep = [a[2][b[2][i]] for i in range(12)]
    eo = [(a[3][b[2][i]] + b[3][i]) % 2 for i in range(12)]
    return cp, co, ep, eo


_TABLE = {}
for _f, _d in _QUARTER.items():
    _acc = (list(range(8)), [0] * 8, list(range(12)), [0] * 12)
    for _n in range(1, 4):
        _acc = _compose(_acc, _d)
        _TABLE[format_move(_f, _n)] = tuple(tuple(x) for x in _acc)

_OPPOSITE = {"U": "D", "D": "U", "R": "L", "L": "R", "F": "B", "B": "F"}


def _apply(state, move):
    cp, co, ep, eo = state
    mcp, mco, mep, meo = _TABLE[move]
    return (
        tuple(cp[mcp[i]] for i in range(8)),
        tuple((co[mcp[i]] + mco[i]) % 3 for i in range(8)),
        tuple(ep[mep[i]] for i in range(12)),
        tuple((eo[mep[i]] + meo[i]) % 2 for i in range(12)),
    )


_SOLVED_EDGES = (tuple(range(12)), (0,) * 12)


def _pack(cube):
    """Pack a 3x3 or a 2x2 into one state shape.

    A 2x2 is packed with its edges already home. That is not a fudge — it is
    the literal truth about the puzzle, and it means the cross, middle-layer
    and last-layer-edge stages report themselves complete without the solver
    needing to know which puzzle it is holding.
    """
    if getattr(cube, "size", 3) == 2:
        return (tuple(cube.cp), tuple(cube.co)) + _SOLVED_EDGES
    return (tuple(cube.cp), tuple(cube.co), tuple(cube.ep), tuple(cube.eo))


def _run(state, seq):
    for m in tokenize(seq):
        state = _apply(state, m)
    return state


def _edge_home(state, i):
    return state[2][i] == i and state[3][i] == 0


def _corner_home(state, i):
    return state[0][i] == i and state[1][i] == 0
