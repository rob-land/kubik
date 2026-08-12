"""Stage names, ordering and completion predicates.

These are the spine of both the solver and the course: a lesson names a
stage, and the goal picture the learner sees plus the check that unlocks
the next card are both generated from that stage's predicate here."""

from __future__ import annotations

from kubik.solver.state import (FIRST_CORNERS, FIRST_EDGES, LAST_CORNERS,
                                LAST_EDGES, MIDDLE_EDGES, _corner_home,
                                _edge_home, _pack)

CROSS = "cross"
FIRST_LAYER = "first-layer"
MIDDLE = "middle"
LL_EDGES_ORIENT = "ll-edges-orient"
LL_CORNERS_ORIENT = "ll-corners-orient"
LL_CORNERS_PERMUTE = "ll-corners-permute"
LL_EDGES_PERMUTE = "ll-edges-permute"

STAGE_TITLES = {
    CROSS: "White cross",
    FIRST_LAYER: "White corners",
    MIDDLE: "Middle layer",
    LL_EDGES_ORIENT: "Yellow cross",
    LL_CORNERS_ORIENT: "Yellow face",
    LL_CORNERS_PERMUTE: "Yellow corners",
    LL_EDGES_PERMUTE: "Last edges",
}

STAGE_ORDER = [CROSS, FIRST_LAYER, MIDDLE, LL_EDGES_ORIENT,
               LL_CORNERS_ORIENT, LL_CORNERS_PERMUTE, LL_EDGES_PERMUTE]

#: A 2x2 is a 3x3 without edges, so it visits only the corner stages. The
#: solver does not special-case this: a 2x2 packs to a state whose edges are
#: already home, which makes the four edge stages complete on arrival.
STAGE_ORDER_2X2 = [FIRST_LAYER, LL_CORNERS_ORIENT, LL_CORNERS_PERMUTE]

STAGE_TITLES_2X2 = {
    FIRST_LAYER: "White face",
    LL_CORNERS_ORIENT: "Yellow face",
    LL_CORNERS_PERMUTE: "Yellow corners",
}


def stage_order(size: int) -> list[str]:
    return STAGE_ORDER_2X2 if size == 2 else STAGE_ORDER


def stage_title(stage: str, size: int = 3) -> str:
    if size == 2:
        return STAGE_TITLES_2X2.get(stage, STAGE_TITLES[stage])
    return STAGE_TITLES[stage]

#: Cubie slots by layer, in the D-first frame.

# --- predicates -------------------------------------------------------------

def cross_done(state):
    return all(_edge_home(state, i) for i in FIRST_EDGES)


def first_layer_done(state):
    return cross_done(state) and all(_corner_home(state, i)
                                     for i in FIRST_CORNERS)


def f2l_done(state):
    return first_layer_done(state) and all(_edge_home(state, i)
                                           for i in MIDDLE_EDGES)


def ll_edges_oriented(state):
    return f2l_done(state) and all(state[3][i] == 0 for i in LAST_EDGES)


def ll_corners_oriented(state):
    return ll_edges_oriented(state) and all(state[1][i] == 0
                                            for i in LAST_CORNERS)


def ll_corners_placed(state):
    return ll_corners_oriented(state) and all(state[0][i] == i
                                              for i in LAST_CORNERS)


def solved(state):
    return ll_corners_placed(state) and all(_edge_home(state, i)
                                            for i in LAST_EDGES)


# A 2x2 has no edges at all, so its predicates look only at corners. The
# packed state still carries an edge half — the corner algorithms churn it as
# they go — and these deliberately ignore it.

def corners_first_layer(state):
    return all(_corner_home(state, i) for i in FIRST_CORNERS)


def corners_oriented(state):
    return corners_first_layer(state) and all(state[1][i] == 0
                                              for i in LAST_CORNERS)


def corners_placed(state):
    return corners_oriented(state) and all(state[0][i] == i
                                           for i in LAST_CORNERS)


#: Stage completion predicates, in solve order — also used by the lesson
#: engine to work out where a learner currently is.
STAGE_DONE = {
    CROSS: cross_done,
    FIRST_LAYER: first_layer_done,
    MIDDLE: f2l_done,
    LL_EDGES_ORIENT: ll_edges_oriented,
    LL_CORNERS_ORIENT: ll_corners_oriented,
    LL_CORNERS_PERMUTE: ll_corners_placed,
    LL_EDGES_PERMUTE: solved,
}

STAGE_DONE_2X2 = {
    FIRST_LAYER: corners_first_layer,
    LL_CORNERS_ORIENT: corners_oriented,
    LL_CORNERS_PERMUTE: corners_placed,
}


def stage_done(size: int) -> dict:
    return STAGE_DONE_2X2 if size == 2 else STAGE_DONE


def current_stage(cube) -> str | None:
    """First stage that is not yet complete, or None if the cube is solved."""
    size = getattr(cube, "size", 3)
    state = _pack(cube)
    done = stage_done(size)
    for stage in stage_order(size):
        if not done[stage](state):
            return stage
    return None


