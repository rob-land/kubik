"""The 2x2: model, solver and course.

A 2x2 is the corner subgroup of a 3x3, so most of these tests are really
checking that the two puzzles cannot drift apart — the corners must move
identically, and the shared solver stages must behave the same.
"""

import random

import pytest

from kubik import curriculum, solver
from kubik.cube import (CORNER_FACELET_2, Cube, Cube2, invert,
                        random_scramble, random_scramble_2x2)


# --- model -------------------------------------------------------------------

def test_solved_2x2():
    cube = Cube2()
    assert cube.is_solved()
    assert cube.size == 2
    assert cube.to_facelets() == [i // 4 for i in range(24)]


def test_every_sticker_belongs_to_exactly_one_corner():
    seen = [i for group in CORNER_FACELET_2 for i in group]
    assert sorted(seen) == list(range(24))


@pytest.mark.parametrize("face", list("URFDLB"))
def test_quarter_turns_have_order_four(face):
    assert Cube2().apply(f"{face} {face} {face} {face}").is_solved()


def test_corners_move_exactly_like_a_3x3():
    """The whole design rests on this: a 2x2 is a 3x3's corners."""
    rng = random.Random(1)
    for _ in range(300):
        scramble = random_scramble(20, rng)
        big, small = Cube().apply(scramble), Cube2().apply(scramble)
        assert big.cp == small.cp
        assert big.co == small.co


def test_facelet_roundtrip():
    rng = random.Random(2)
    for _ in range(400):
        cube = Cube2().apply(random_scramble_2x2(15, rng))
        assert Cube2.from_facelets(cube.to_facelets()) == cube


def test_from_facelets_rejects_nonsense():
    with pytest.raises(ValueError):
        Cube2.from_facelets([0] * 24)
    with pytest.raises(ValueError):
        Cube2.from_facelets([0] * 54)


def test_from_facelets_rejects_a_single_twisted_corner():
    cube = Cube2()
    cube.co[0] = 1
    with pytest.raises(ValueError):
        cube.validate()


def test_invert_undoes():
    rng = random.Random(3)
    for _ in range(200):
        scramble = random_scramble_2x2(15, rng)
        assert Cube2().apply(scramble).apply(invert(scramble)).is_solved()


def test_2x2_scramble_uses_only_three_faces():
    """WCA 2x2 notation leaves out the redundant opposite faces."""
    rng = random.Random(4)
    for _ in range(200):
        moves = random_scramble_2x2(11, rng)
        assert len(moves) == 11
        faces = [m[0] for m in moves]
        assert set(faces) <= set("URF")
        for i in range(1, len(faces)):
            assert faces[i] != faces[i - 1]


def test_3x3_scramble_leaves_the_back_bottom_left_corner_alone():
    """A consequence of U/R/F-only scrambles, and why no frame is needed."""
    rng = random.Random(5)
    for _ in range(200):
        cube = Cube2().apply(random_scramble_2x2(15, rng))
        assert cube.cp[6] == 6 and cube.co[6] == 0


# --- solver -------------------------------------------------------------------

def _solution(cube):
    return [m for step in solver.solve(cube) for m in step.moves]


def test_solved_2x2_needs_no_steps():
    assert solver.solve(Cube2()) == []
    assert solver.current_stage(Cube2()) is None


@pytest.mark.parametrize("seed", range(6))
def test_solves_random_2x2_scrambles(seed):
    rng = random.Random(seed)
    for _ in range(60):
        scramble = random_scramble_2x2(13, rng)
        cube = Cube2().apply(scramble)
        assert Cube2().apply(scramble).apply(_solution(cube)).is_solved(), \
            " ".join(scramble)


def test_solves_states_a_smart_cube_could_report():
    """Hardware reports whatever the owner did, including D, L and B turns."""
    rng = random.Random(7)
    for _ in range(200):
        scramble = random_scramble(20, rng)
        cube = Cube2().apply(scramble)
        assert Cube2().apply(scramble).apply(_solution(cube)).is_solved(), \
            " ".join(scramble)


def test_only_the_corner_stages_are_used():
    rng = random.Random(8)
    seen = set()
    for _ in range(120):
        cube = Cube2().apply(random_scramble_2x2(13, rng))
        for step in solver.solve(cube):
            seen.add(step.stage)
    assert seen <= set(solver.STAGE_ORDER_2X2)
    assert solver.CROSS not in seen
    assert solver.MIDDLE not in seen
    assert solver.LL_EDGES_PERMUTE not in seen


def test_solution_length_stays_human():
    rng = random.Random(9)
    lengths = [len(_solution(Cube2().apply(random_scramble_2x2(13, rng))))
               for _ in range(80)]
    average = sum(lengths) / len(lengths)
    assert 25 < average < 70, average
    assert max(lengths) < 120


def test_stage_titles_differ_from_the_3x3():
    assert solver.stage_title(solver.FIRST_LAYER, 2) == "White face"
    assert solver.stage_title(solver.FIRST_LAYER, 3) == "White corners"
    assert solver.stage_order(2) == solver.STAGE_ORDER_2X2
    assert solver.stage_order(3) == solver.STAGE_ORDER


def test_current_stage_walks_forward():
    rng = random.Random(10)
    cube = Cube2().apply(random_scramble_2x2(13, rng))
    seen = []
    for step in solver.solve(cube):
        stage = solver.current_stage(cube)
        if stage not in seen:
            seen.append(stage)
        cube.apply(step.moves)
    assert seen == [s for s in solver.STAGE_ORDER_2X2 if s in seen]
    assert solver.current_stage(cube) is None


def test_3x3_solver_is_unaffected():
    rng = random.Random(11)
    for _ in range(60):
        scramble = random_scramble(25, rng)
        cube = Cube().apply(scramble)
        assert Cube().apply(scramble).apply(_solution(cube)).is_solved()


# --- course --------------------------------------------------------------------

def test_two_tracks():
    assert [p[0] for p in curriculum.PUZZLES] == ["3x3", "2x2"]
    three = curriculum.load("3x3")
    two = curriculum.load("2x2")
    assert three and two
    assert all(l.size == 3 for l in three)
    assert all(l.size == 2 for l in two)
    assert len(curriculum.load()) == len(three) + len(two)


def test_2x2_lesson_goals_are_reachable_and_masked_at_24():
    for lesson in curriculum.load("2x2"):
        if not lesson.goal:
            continue
        mask = curriculum.goal_mask(lesson.goal, 2)
        assert len(mask) == 24
        assert Cube2().matches(mask)
        assert curriculum.goal_predicate(lesson.goal, 2)(Cube2())


def test_2x2_goal_masks_grow_monotonically():
    """Each step should pin down at least as much as the one before it."""
    pinned = -1
    for stage in solver.STAGE_ORDER_2X2:
        mask = curriculum.goal_mask(stage, 2)
        count = sum(1 for m in mask if m >= 0)
        assert count > pinned
        pinned = count
    assert pinned == 24  # the last stage pins the whole cube


def test_2x2_goals_are_not_satisfied_by_a_scrambled_cube():
    rng = random.Random(12)
    cube = Cube2().apply(random_scramble_2x2(13, rng))
    unmet = [stage for stage in solver.STAGE_ORDER_2X2
             if not curriculum.goal_predicate(stage, 2)(cube)]
    assert unmet, "a scramble should leave something to do"


def test_2x2_taught_algorithms_match_the_solver():
    algs = {}
    for lesson in curriculum.load("2x2"):
        for card in lesson.cards:
            if card.kind == "alg":
                algs[card.alg_name] = card.moves.split()
    assert algs["Right-hand algorithm"] == ["R", "U", "R'", "U'"]
    assert algs["Corner twist"] == solver.SUNE
    assert algs["Corner cycle"] == solver.APERM[0]
