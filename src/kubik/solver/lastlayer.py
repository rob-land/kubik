"""The last layer: orient edges, orient corners, permute corners, permute
edges.

Every case is reached by a short run of `U^k + algorithm`, so one small
breadth-first search replaces four separate case tables."""

from __future__ import annotations

from kubik.cube import format_move, tokenize
from kubik.solver.stages import (LL_CORNERS_ORIENT, LL_CORNERS_PERMUTE,
                                 LL_EDGES_ORIENT, LL_EDGES_PERMUTE,
                                 corners_oriented, corners_placed,
                                 ll_corners_oriented, ll_corners_placed,
                                 ll_edges_oriented, solved)
from kubik.solver.state import Step, Unsolvable, _run

# --- stages 4-7: the last layer ---------------------------------------------
# Every case is reached by a short sequence of `U^k + algorithm`, so one small
# breadth-first search replaces four separate case tables.

EOLL = tokenize("F R U R' U' F'")
SUNE = tokenize("R U R' U R U2 R'")
APERM = [tokenize("R' F R' B2 R F' R' B2 R2"),
         tokenize("R B' R F2 R' B R F2 R2")]
UPERM = [tokenize("R U' R U R U R U' R' U' R2"),
         tokenize("R2 U R U R' U' R' U' R' U R'")]


def _ll_search(state, algs, goal, max_apps):
    frontier = [(state, [])]
    for _ in range(max_apps + 1):
        nxt = []
        for st, seq in frontier:
            for d in range(4):
                setup = [format_move("U", d)] if d else []
                base = _run(st, setup)
                if goal(base):
                    return seq + setup
                for alg in algs:
                    nxt.append((_run(base, alg), seq + setup + list(alg)))
        frontier = nxt
    return None


_LL_PLAN = [
    (LL_EDGES_ORIENT, [EOLL], ll_edges_oriented, 3, "Make the yellow cross"),
    (LL_CORNERS_ORIENT, [SUNE], ll_corners_oriented, 4,
     "Finish the yellow face"),
    (LL_CORNERS_PERMUTE, APERM, ll_corners_placed, 2,
     "Put the yellow corners in place"),
    (LL_EDGES_PERMUTE, UPERM, solved, 2, "Put the last edges in place"),
]


def _solve_last_layer(state, steps, plan=None):
    for stage, algs, goal, depth, label in (plan or _LL_PLAN):
        if goal(state):
            continue
        seq = _ll_search(state, algs, goal, depth)
        if seq is None:
            raise Unsolvable(stage)
        state = _run(state, seq)
        steps.append(Step(stage, label, seq))
    return state


_LL_PLAN_2X2 = [
    (LL_CORNERS_ORIENT, [SUNE], corners_oriented, 4, "Finish the yellow face"),
    (LL_CORNERS_PERMUTE, APERM, corners_placed, 2,
     "Put the yellow corners in place"),
]


def _always(_state):
    return True


