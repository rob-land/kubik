"""The course: lessons as data, checked against live cube state.

The shape is lifted from CubeStation's `lesson_lbllessons.json`, whose whole
engine is a 54-entry facelet mask with -1 for "don't care" plus a required
holding orientation. Goal masks here are *derived* from the solver's own stage
predicates rather than hand-written, so a lesson can never disagree with the
solver about what "white cross" means.

The teaching devices — quiz before algorithm, a named algorithm reused across
steps, specific corrections rather than "try again" — come from GoCube's
`Particula.Learn`, which is a condition interpreter over live cube state rather
than a video player.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

from kubik.cube import CORNER_FACELET, CORNER_FACELET_2, EDGE_FACELET, Cube, Cube2
from kubik import solver

# --- goal masks derived from the solver's stages ----------------------------

_SOLVED = Cube().to_facelets()
_SOLVED_2 = Cube2().to_facelets()


_AFTER = {stage: solver.STAGE_ORDER[solver.STAGE_ORDER.index(stage):]
          for stage in solver.STAGE_ORDER}


def _facelets_for(stage: str) -> set[int]:
    """Which stickers the goal picture for a stage should pin down."""
    reached = solver.STAGE_ORDER[:solver.STAGE_ORDER.index(stage) + 1]
    keep = {31}  # the D centre — the first layer is white, on the bottom
    edges = list(solver.FIRST_EDGES)
    corners: list[int] = []
    if solver.FIRST_LAYER in reached:
        corners += list(solver.FIRST_CORNERS)
    if solver.MIDDLE in reached:
        edges += list(solver.MIDDLE_EDGES)
    if solver.LL_EDGES_ORIENT in reached:
        keep.add(4)  # the U centre
        keep.update(EDGE_FACELET[i][0] for i in solver.LAST_EDGES)
    if solver.LL_CORNERS_ORIENT in reached:
        keep.update(CORNER_FACELET[i][0] for i in solver.LAST_CORNERS)
    if solver.LL_CORNERS_PERMUTE in reached:
        corners += list(solver.LAST_CORNERS)
    if solver.LL_EDGES_PERMUTE in reached:
        edges += list(solver.LAST_EDGES)
    for i in edges:
        keep.update(EDGE_FACELET[i])
    for i in corners:
        keep.update(CORNER_FACELET[i])
    return keep


def _facelets_for_2x2(stage: str) -> set[int]:
    reached = solver.STAGE_ORDER_2X2[
        :solver.STAGE_ORDER_2X2.index(stage) + 1]
    keep: set[int] = set()
    for i in solver.FIRST_CORNERS:
        keep.update(CORNER_FACELET_2[i])
    if solver.LL_CORNERS_ORIENT in reached:
        keep.update(CORNER_FACELET_2[i][0] for i in solver.LAST_CORNERS)
    if solver.LL_CORNERS_PERMUTE in reached:
        for i in solver.LAST_CORNERS:
            keep.update(CORNER_FACELET_2[i])
    return keep


def stage_mask(stage: str, size: int = 3) -> list[int]:
    """A lesson mask picturing the goal of one stage — 54 cells, or 24."""
    if size == 2:
        keep = _facelets_for_2x2(stage)
        return [_SOLVED_2[i] if i in keep else -1 for i in range(24)]
    keep = _facelets_for(stage)
    return [_SOLVED[i] if i in keep else -1 for i in range(54)]


def daisy_mask() -> list[int]:
    """Four white edges around the yellow centre, on the top face."""
    mask = [-1] * 54
    mask[4] = 0  # yellow centre
    for slot in solver.LAST_EDGES:
        mask[EDGE_FACELET[slot][0]] = 3  # a white sticker facing up
    return mask


def daisy_done(cube: Cube) -> bool:
    """Each white (D-layer) edge sits in the U layer with white facing up."""
    for edge in solver.FIRST_EDGES:
        slot = cube.ep.index(edge)
        if slot not in solver.LAST_EDGES or cube.eo[slot] != 0:
            return False
    return True


#: Extra goals that are not one of the solver's stages.
CUSTOM_GOALS = {
    "daisy": (daisy_done, daisy_mask),
}


def goal_predicate(goal: str, size: int = 3):
    if goal in CUSTOM_GOALS:
        return CUSTOM_GOALS[goal][0]
    done = solver.stage_done(size)[goal]
    return lambda cube: done(solver._pack(cube))


def goal_mask(goal: str, size: int = 3) -> list[int]:
    if goal in CUSTOM_GOALS:
        return CUSTOM_GOALS[goal][1]()
    return stage_mask(goal, size)


# --- lesson model -----------------------------------------------------------

@dataclass
class Card:
    """One screen inside a lesson."""

    kind: str                      # text | alg | quiz | do
    text: str = ""
    title: str = ""
    moves: str = ""
    alg_name: str = ""
    question: str = ""
    options: list[str] = field(default_factory=list)
    answer: int = 0
    corrections: list[str] = field(default_factory=list)
    goal: str = ""
    call: str = ""
    hold: str = ""


@dataclass
class Lesson:
    id: str
    title: str
    summary: str
    cards: list[Card]
    cube: str = "3x3"

    @property
    def size(self) -> int:
        return 2 if self.cube == "2x2" else 3

    @property
    def goal(self) -> str:
        for card in reversed(self.cards):
            if card.goal:
                return card.goal
        return ""


#: The puzzles the course covers, in the order they are offered.
PUZZLES = [("3x3", "3×3"), ("2x2", "2×2")]


def load(cube: str | None = None) -> list[Lesson]:
    raw = json.loads(
        resources.files("kubik").joinpath("data/curriculum.json")
        .read_text(encoding="utf-8"))
    lessons = []
    for entry in raw["lessons"]:
        cards = [Card(**card) for card in entry["cards"]]
        lesson = Lesson(entry["id"], entry["title"], entry.get("summary", ""),
                        cards, entry.get("cube", "3x3"))
        if cube is None or lesson.cube == cube:
            lessons.append(lesson)
    return lessons
