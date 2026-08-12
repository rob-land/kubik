"""The layer-by-layer solver has to be right for every state, not most."""

import random

import pytest

from kubik import curriculum, solver
from kubik.cube import Cube, random_scramble


def _solution(cube):
    return [m for step in solver.solve(cube) for m in step.moves]


def test_solved_cube_needs_no_steps():
    assert solver.solve(Cube()) == []
    assert solver.current_stage(Cube()) is None


@pytest.mark.parametrize("seed", range(6))
def test_solves_random_scrambles(seed):
    rng = random.Random(seed)
    for _ in range(40):
        scramble = random_scramble(25, rng)
        cube = Cube().apply(scramble)
        assert Cube().apply(scramble).apply(_solution(cube)).is_solved(), \
            " ".join(scramble)


def test_solves_hard_edge_cases():
    """States that previously broke a stage: superflip, and pure last layers."""
    cases = [
        "U R2 F B R B2 R U2 L B2 R U' D' R2 F R' L B2 U2 F2",  # superflip
        "R U R' U R U2 R'",                                     # sune only
        "F R U R' U' F'",                                       # eoll only
        "R' F R' B2 R F' R' B2 R2",                             # corner cycle
        "R U' R U R U R U' R' U' R2",                           # edge cycle
        "U", "D2", "R L' U D' F B'",
    ]
    for scramble in cases:
        cube = Cube().apply(scramble)
        assert Cube().apply(scramble).apply(_solution(cube)).is_solved(), \
            scramble


def test_stages_are_reached_in_order():
    """Each step must leave every earlier stage still complete."""
    rng = random.Random(99)
    for _ in range(40):
        cube = Cube().apply(random_scramble(25, rng))
        reached = []
        for step in solver.solve(cube):
            cube.apply(step.moves)
            if step.stage not in reached:
                reached.append(step.stage)
            index = solver.STAGE_ORDER.index(step.stage)
            state = solver._pack(cube)
            for earlier in solver.STAGE_ORDER[:index]:
                assert solver.STAGE_DONE[earlier](state), \
                    f"{step.stage} broke {earlier}"
        assert reached == [s for s in solver.STAGE_ORDER if s in reached]


def test_solution_length_stays_human():
    rng = random.Random(5)
    lengths = []
    for _ in range(60):
        cube = Cube().apply(random_scramble(25, rng))
        lengths.append(len(_solution(cube)))
    average = sum(lengths) / len(lengths)
    # Beginner layer-by-layer normally lands between 100 and 140 moves.
    assert 90 < average < 150, average
    assert max(lengths) < 260


def test_steps_are_cancelled():
    rng = random.Random(6)
    for _ in range(30):
        cube = Cube().apply(random_scramble(25, rng))
        for step in solver.solve(cube):
            faces = [m[0] for m in step.moves]
            for i in range(1, len(faces)):
                assert faces[i] != faces[i - 1], step.moves


def test_taught_algorithms_are_the_ones_the_solver_uses():
    """The course would be lying if these drifted apart."""
    algs = {}
    for lesson in curriculum.load():
        for card in lesson.cards:
            if card.kind == "alg":
                algs[card.alg_name] = card.moves.split()
    assert algs["Right-hand algorithm"] == ["R", "U", "R'", "U'"]
    assert algs["Insert right"] == solver.INSERT_RIGHT
    assert algs["Insert left"] == solver.INSERT_LEFT
    assert algs["Cross algorithm"] == solver.EOLL
    assert algs["Corner twist"] == solver.SUNE
    assert algs["Corner cycle"] == solver.APERM[0]
    assert algs["Edge cycle"] == solver.UPERM[0]
    # The right-hand algorithm must genuinely serve the front-right slot.
    assert solver._right_hand_alg(4) == ["R", "U", "R'", "U'"]


def test_next_hint_names_the_current_stage():
    cube = Cube().apply("R U R' U' F2 L2 D B'")
    hint = solver.next_hint(cube)
    assert hint is not None
    assert hint.stage == solver.current_stage(cube)
    assert hint.moves


def test_unsolvable_state_raises():
    cube = Cube()
    cube.co[0] = 1  # a single twisted corner cannot happen on a real cube
    with pytest.raises(Exception):
        solver.solve(cube)
