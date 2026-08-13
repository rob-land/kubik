"""Hand entry: the inference has to be both helpful and never wrong.

Wrong is the dangerous failure. A deduction that quietly fills the wrong
colour would hand the solver a cube the user never had, so most of these
tests check that whatever gets deduced matches the cube the stickers actually
came from.
"""

import random

import pytest

from kubik.cube import Cube, random_scramble
from kubik.facelets import CENTRES, PartialCube

FREE = [i for i in range(54) if i not in CENTRES]


def _enter(target, order):
    """Type stickers in `order`, skipping any the app has already worked out."""
    partial = PartialCube()
    typed = 0
    for index in order:
        if partial.facelets[index] is not None:
            continue
        partial.set(index, target[index])
        typed += 1
        if partial.complete:
            break
    return partial, typed


# --- the basics --------------------------------------------------------------

def test_centres_are_known_from_the_start():
    partial = PartialCube()
    assert partial.entered == 0
    for face, centre in enumerate(CENTRES):
        assert partial.facelets[centre] == face
    assert sum(1 for v in partial.facelets if v is not None) == 6


def test_centres_cannot_be_painted():
    partial = PartialCube()
    partial.set(CENTRES[0], 3)
    assert partial.facelets[CENTRES[0]] == 0


def test_a_fresh_cube_allows_anything():
    partial = PartialCube()
    assert partial.candidates(8) == {0, 1, 2, 3, 4, 5}
    assert partial.remaining(0) == 8      # the white centre is already placed


def test_editing_retracts_stale_deductions():
    """A correction must not leave earlier inferences behind."""
    target = Cube().apply("R U R' U' F2 L").to_facelets()
    partial = PartialCube()
    for index in FREE:
        partial.set(index, target[index])
    assert partial.complete
    partial.set(FREE[0], None)
    partial.set(FREE[1], None)
    # Whatever it now shows must still be derived from what is left.
    for index in FREE:
        if partial.facelets[index] is not None:
            assert partial.facelets[index] == target[index]


# --- deduction is correct ----------------------------------------------------

@pytest.mark.parametrize("seed", range(4))
def test_deductions_match_the_real_cube_random_order(seed):
    rng = random.Random(seed)
    for _ in range(5):
        target = Cube().apply(random_scramble(25, rng)).to_facelets()
        order = list(FREE)
        rng.shuffle(order)
        partial, _ = _enter(target, order)
        assert partial.complete
        assert partial.facelets == target


def test_deductions_match_the_real_cube_face_by_face():
    rng = random.Random(99)
    for _ in range(10):
        target = Cube().apply(random_scramble(25, rng)).to_facelets()
        partial, _ = _enter(target, FREE)
        assert partial.complete
        assert partial.facelets == target
        assert partial.to_cube() == Cube.from_facelets(target)


def test_a_solved_cube_can_be_entered():
    target = Cube().to_facelets()
    partial, _ = _enter(target, FREE)
    assert partial.facelets == target
    assert partial.to_cube().is_solved()


# --- deduction is useful -----------------------------------------------------

def test_typing_is_meaningfully_shorter_than_48():
    rng = random.Random(3)
    typed = []
    for _ in range(10):
        target = Cube().apply(random_scramble(25, rng)).to_facelets()
        typed.append(_enter(target, FREE)[1])
    average = sum(typed) / len(typed)
    assert average < 40, average          # 48 stickers, well under
    assert max(typed) <= 44


def test_the_last_faces_mostly_fill_themselves():
    """Entering face by face, the back face should be nearly free."""
    rng = random.Random(5)
    last_face_typed = []
    for _ in range(10):
        target = Cube().apply(random_scramble(25, rng)).to_facelets()
        partial = PartialCube()
        for face in range(6):
            typed = 0
            for index in range(face * 9, face * 9 + 9):
                if index in CENTRES or partial.facelets[index] is not None:
                    continue
                partial.set(index, target[index])
                typed += 1
            if face == 5:
                last_face_typed.append(typed)
        assert partial.facelets == target
    assert sum(last_face_typed) / len(last_face_typed) < 3


def test_deduced_stickers_are_flagged_separately():
    rng = random.Random(8)
    target = Cube().apply(random_scramble(25, rng)).to_facelets()
    partial, typed = _enter(target, FREE)
    assert partial.deduced, "nothing was inferred at all"
    assert len(partial.deduced) == 48 - typed
    for index in partial.deduced:
        assert not partial.is_user_set(index)


# --- errors are caught and localised -----------------------------------------

def test_two_stickers_of_one_colour_on_a_corner_is_rejected():
    partial = PartialCube()
    partial.set(8, 0)      # URF, the U facelet
    partial.set(9, 0)      # URF, the R facelet — no corner has two whites
    ready, message = partial.status()
    assert not ready
    assert "URF" in message


def test_a_tenth_sticker_of_a_colour_is_rejected():
    partial = PartialCube()
    whites = 0
    for index in FREE:
        if whites == 9:
            break
        if partial.candidates(index) and 0 in partial.candidates(index):
            partial.set(index, 0)
            whites += 1
    assert partial.problem or partial.remaining(0) == 0


def test_status_reports_progress_then_readiness():
    partial = PartialCube()
    ready, message = partial.status()
    assert not ready and "48 to go" in message

    target = Cube().apply("R U F").to_facelets()
    for index in FREE:
        partial.set(index, target[index])
    ready, message = partial.status()
    assert ready and "Ready to solve" in message


def test_incomplete_cube_cannot_be_converted():
    with pytest.raises(ValueError):
        PartialCube().to_cube()


def test_an_impossible_cube_is_rejected_rather_than_solved():
    """A single flipped edge is a real cube's stickers rearranged illegally."""
    facelets = Cube().to_facelets()
    a, b = 5, 10       # the two stickers of the UR edge
    facelets[a], facelets[b] = facelets[b], facelets[a]
    partial = PartialCube()
    for index in FREE:
        partial.set(index, facelets[index])
    ready, message = partial.status()
    assert not ready
    assert "parity" in message or "cannot exist" in message or "real" in message


# --- the whole point ---------------------------------------------------------

def test_an_entered_cube_solves():
    rng = random.Random(21)
    for _ in range(5):
        scramble = random_scramble(25, rng)
        target = Cube().apply(scramble).to_facelets()
        partial, _ = _enter(target, FREE)
        cube = partial.to_cube()
        from kubik.solver import solve
        moves = [m for step in solve(cube) for m in step.moves]
        assert Cube.from_facelets(target).apply(moves).is_solved()
