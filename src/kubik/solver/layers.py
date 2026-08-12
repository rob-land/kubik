"""The first two and a half layers: cross, first-layer corners, middle edges.

The cross is searched for outright — it is short enough that a bounded
depth-first walk beats a pile of special cases for flipped and mis-slotted
edges. The corner and middle-edge insertions are the textbook algorithms,
with every candidate verified against the real state before it is used."""

from __future__ import annotations

from kubik.cube import Cube, cancel, format_move, rotate_alg, tokenize
from kubik.solver.stages import (CROSS, FIRST_LAYER, MIDDLE, cross_done,
                                 first_layer_done)
from kubik.solver.state import (ALL_MOVES, FIRST_CORNERS, FIRST_EDGES,
                                MIDDLE_EDGES, Step, Unsolvable, _OPPOSITE,
                                _apply, _corner_home, _edge_home, _pack,
                                _run)

# --- stage 1: the cross -----------------------------------------------------
# Short enough to search for outright, which keeps the move count human and
# avoids a pile of special cases for flipped and mis-slotted edges.

def _cross_search(state, solved_edges, depth):
    """Exact-depth DFS for a sequence that solves one more cross edge."""
    targets = [i for i in FIRST_EDGES if i not in solved_edges]

    def rec(st, left, prev, seq):
        if left == 0:
            if any(not _edge_home(st, i) for i in solved_edges):
                return None
            for t in targets:
                if _edge_home(st, t):
                    return seq
            return None
        for move in ALL_MOVES:
            face = move[0]
            if face == prev:
                continue
            # Fix the order of commuting opposite faces to halve the tree.
            if prev and _OPPOSITE[face] == prev and face > prev:
                continue
            found = rec(_apply(st, move), left - 1, face, seq + [move])
            if found is not None:
                return found
        return None

    return rec(state, depth, "", [])


_EDGE_LABEL = {4: "right", 5: "front", 6: "left", 7: "back"}


def _solve_cross(state, steps):
    done = {i for i in FIRST_EDGES if _edge_home(state, i)}
    while len(done) < 4:
        for depth in range(1, 7):
            seq = _cross_search(state, done, depth)
            if seq is not None:
                break
        else:
            raise Unsolvable("cross")
        state = _run(state, seq)
        newly = [i for i in FIRST_EDGES
                 if _edge_home(state, i) and i not in done]
        done.update(newly)
        names = ", ".join(_EDGE_LABEL[i] for i in sorted(newly))
        steps.append(Step(CROSS, f"Place the {names} white edge", seq))
    return state


# --- stage 2: first-layer corners -------------------------------------------

def _slot_of(alg):
    after = _run(_pack(Cube()), alg)
    moved = [i for i in FIRST_CORNERS
             if after[0][i] != i or after[1][i] != 0]
    assert len(moved) == 1, (alg, moved)
    return moved[0]


def _discover_corner_algs():
    """For each first-layer slot, the right- and left-hand faces that serve it."""
    right, left = {}, {}
    for face in "FRBL":
        right[_slot_of([face, "U", face + "'", "U'"])] = face
        left[_slot_of([face + "'", "U'", face, "U"])] = face
    assert len(right) == len(left) == 4
    return right, left


_RH_FACE, _LH_FACE = _discover_corner_algs()

_CORNER_LABEL = {4: "front-right", 5: "front-left",
                 6: "back-left", 7: "back-right"}


def _corner_candidates(target):
    """Insertions worth trying for a first-layer slot.

    The repeated right-hand algorithm is what the course teaches, but a corner
    that arrives badly twisted needs it five times. The three-move conjugate
    insertions cover those cases in a quarter of the moves, and every candidate
    is verified against the real state before it is used, so offering extra
    shapes is safe.
    """
    x, y = _RH_FACE[target], _LH_FACE[target]
    rh = [x, "U", x + "'", "U'"]
    lh = [y + "'", "U'", y, "U"]
    for turn in ("U", "U'", "U2"):
        for face in (x, y):
            yield [face, turn, face + "'"]
            yield [face + "'", turn, face]
    for reps in range(1, 7):
        yield rh * reps
        yield lh * reps


def _right_hand_alg(target):
    face = _RH_FACE[target]
    return [face, "U", face + "'", "U'"]


def _solve_first_layer(state, steps, keep=cross_done):
    """`keep` is the earlier work an insertion must not break — the cross on a
    3x3, nothing at all on a 2x2."""
    for target in FIRST_CORNERS:
        if _corner_home(state, target):
            continue
        slot = state[0].index(target)
        if slot in FIRST_CORNERS:
            # Stuck in the first layer, wrong slot or twisted: the right-hand
            # algorithm for that slot lifts it into the U layer.
            eject = _right_hand_alg(slot)
            state = _run(state, eject)
            steps.append(Step(FIRST_LAYER,
                              f"Free the {_CORNER_LABEL[target]} white corner",
                              list(eject)))
        seq = _place_corner(state, target, keep)
        if seq is None:
            raise Unsolvable("first layer")
        state = _run(state, seq)
        steps.append(Step(FIRST_LAYER,
                          f"Insert the {_CORNER_LABEL[target]} white corner",
                          seq))
    return state


def _place_corner(state, target, keep=cross_done):
    """Shortest verified insertion of one first-layer corner."""
    guard = [i for i in FIRST_CORNERS
             if i != target and _corner_home(state, i)]
    best = None
    for d in range(4):
        setup = [format_move("U", d)] if d else []
        base = _run(state, setup)
        for alg in _corner_candidates(target):
            if best is not None and len(setup) + len(alg) >= len(best):
                continue
            after = _run(base, alg)
            if not _corner_home(after, target) or not keep(after):
                continue
            if any(not _corner_home(after, i) for i in guard):
                continue
            best = cancel(setup + list(alg))
    return best


# --- stage 3: middle-layer edges --------------------------------------------
# The two textbook insertions, rotated about y for each front face.

INSERT_RIGHT = tokenize("U R U' R' U' F' U F")   # -> FR slot
INSERT_LEFT = tokenize("U' L' U L U F U' F'")    # -> FL slot

_MIDDLE_LABEL = {8: "front-right", 9: "front-left",
                 10: "back-left", 11: "back-right"}


def _middle_candidates():
    for k in range(4):
        for alg in (INSERT_RIGHT, INSERT_LEFT):
            yield rotate_alg(alg, k)


def _solve_middle(state, steps):
    for target in MIDDLE_EDGES:
        if _edge_home(state, target):
            continue
        seq = _insert_middle(state, target)
        if seq is None:
            # A wrong edge is occupying the slot; kick it out and retry.
            slot = state[2].index(target)
            if slot not in MIDDLE_EDGES:
                raise Unsolvable("middle layer")
            kick = _kick_middle(state, slot)
            state = _run(state, kick)
            steps.append(Step(MIDDLE,
                              f"Free the {_MIDDLE_LABEL[target]} edge", kick))
            seq = _insert_middle(state, target)
            if seq is None:
                raise Unsolvable("middle layer")
        state = _run(state, seq)
        steps.append(Step(MIDDLE,
                          f"Insert the {_MIDDLE_LABEL[target]} edge", seq))
    return state


def _insert_middle(state, target):
    guard = [i for i in MIDDLE_EDGES if i != target and _edge_home(state, i)]
    best = None
    for d in range(4):
        setup = [format_move("U", d)] if d else []
        base = _run(state, setup)
        for alg in _middle_candidates():
            after = _run(base, alg)
            if not (_edge_home(after, target) and first_layer_done(after)):
                continue
            if any(not _edge_home(after, i) for i in guard):
                continue
            candidate = cancel(setup + list(alg))
            if best is None or len(candidate) < len(best):
                best = candidate
    return best


def _kick_middle(state, slot):
    """Any insertion that displaces whatever is sitting in `slot`."""
    occupant = state[2][slot]
    for alg in _middle_candidates():
        if _run(state, alg)[2].index(occupant) != slot:
            return list(alg)
    raise Unsolvable("middle layer")


