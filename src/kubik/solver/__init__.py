"""Layer-by-layer solver that produces *teachable* solutions.

CubeStation ships two solvers: a Kociemba two-phase `cs::Search` for "just
solve it", and a separate `cs::HumanSolverLBL` whose stages are named
solveDCross / solveDLayer / solveMLayer / solveUCross / solveUFace /
solveUCorner / solveFinal. Only the second one can teach — a 20-move two-phase
solution has no explicable structure. This package is the equivalent of the
second one, and it follows the same D-first stage order.

The first layer is D (white), the last layer is U (yellow), which is how every
beginner tutorial holds the cube. That choice matters more than it looks: it
means every algorithm the course teaches is the textbook one, so "the
right-hand algorithm" is literally `R U R' U'` in the lesson, in the hint, and
in the solver's own output.

A 2x2 solves through the same three corner stages with the edge stages
dropped; see `_solve_2x2`.

Output is run through `cube.cancel` before it is shown, matching
CubeStation's `mergeRepetedFormula` pass.
"""

from __future__ import annotations

from kubik.cube import Cube, cancel

from kubik.solver.lastlayer import (APERM, EOLL, SUNE, UPERM, _LL_PLAN,
                                    _LL_PLAN_2X2, _ll_search,
                                    _solve_last_layer)
from kubik.solver.layers import (INSERT_LEFT, INSERT_RIGHT, _CORNER_LABEL,
                                 _LH_FACE, _RH_FACE, _corner_candidates,
                                 _cross_search, _insert_middle, _kick_middle,
                                 _place_corner, _right_hand_alg,
                                 _solve_cross, _solve_first_layer,
                                 _solve_middle)
from kubik.solver.stages import (CROSS, FIRST_LAYER, LL_CORNERS_ORIENT,
                                 LL_CORNERS_PERMUTE, LL_EDGES_ORIENT,
                                 LL_EDGES_PERMUTE, MIDDLE, STAGE_DONE,
                                 STAGE_DONE_2X2, STAGE_ORDER, STAGE_ORDER_2X2,
                                 STAGE_TITLES, STAGE_TITLES_2X2,
                                 corners_first_layer, corners_oriented,
                                 corners_placed, cross_done, current_stage,
                                 f2l_done, first_layer_done,
                                 ll_corners_oriented, ll_corners_placed,
                                 ll_edges_oriented, solved, stage_done,
                                 stage_order, stage_title)
from kubik.solver.state import (ALL_MOVES, FIRST_CORNERS, FIRST_EDGES,
                                LAST_CORNERS, LAST_EDGES, MIDDLE_EDGES, Step,
                                Unsolvable, _pack, _run)

__all__ = [
    "CROSS", "FIRST_LAYER", "MIDDLE", "LL_EDGES_ORIENT", "LL_CORNERS_ORIENT",
    "LL_CORNERS_PERMUTE", "LL_EDGES_PERMUTE",
    "STAGE_ORDER", "STAGE_ORDER_2X2", "STAGE_TITLES", "STAGE_TITLES_2X2",
    "STAGE_DONE", "STAGE_DONE_2X2",
    "FIRST_CORNERS", "FIRST_EDGES", "LAST_CORNERS", "LAST_EDGES",
    "MIDDLE_EDGES",
    "INSERT_LEFT", "INSERT_RIGHT", "EOLL", "SUNE", "APERM", "UPERM",
    "Step", "Unsolvable",
    "current_stage", "stage_done", "stage_order", "stage_title",
    "solve", "solve_moves", "next_hint",
]


def _always(_state):
    return True


def solve(cube) -> list[Step]:
    """Full layer-by-layer solution of a 3x3 or a 2x2, as explicable steps."""
    if getattr(cube, "size", 3) == 2:
        return _finish(_solve_2x2(_pack(cube)))
    state = _pack(cube)
    steps: list[Step] = []
    state = _solve_cross(state, steps)
    state = _solve_first_layer(state, steps)
    state = _solve_middle(state, steps)
    state = _solve_last_layer(state, steps)
    if not solved(state):
        raise Unsolvable("final")
    return _finish(steps)


def _solve_2x2(state) -> list[Step]:
    """The same three corner stages a 3x3 uses, with the edge stages dropped.

    The corner algorithms churn the edge half of the packed state as they go,
    so every predicate on this path ignores it.
    """
    steps: list[Step] = []
    state = _solve_first_layer(state, steps, keep=_always)
    state = _solve_last_layer(state, steps, _LL_PLAN_2X2)
    if not corners_placed(state):
        raise Unsolvable("2x2")
    return steps


def _finish(steps: list[Step]) -> list[Step]:
    for step in steps:
        step.moves = cancel(step.moves)
    return [s for s in steps if s.moves]


def solve_moves(cube: Cube) -> list[str]:
    return cancel([m for step in solve(cube) for m in step.moves])


def next_hint(cube: Cube) -> Step | None:
    """The first step of the solution — what to tell a stuck learner."""
    steps = solve(cube)
    return steps[0] if steps else None
