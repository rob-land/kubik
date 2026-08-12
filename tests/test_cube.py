"""Cube model: moves, facelets, notation."""

import random

import pytest

from kubik.cube import (Cube, CORNER_FACELET, EDGE_FACELET, cancel, format_move,
                        invert, random_scramble, rotate_alg, tokenize)


def test_solved_cube():
    cube = Cube()
    assert cube.is_solved()
    assert cube.to_facelets() == [i // 9 for i in range(54)]


@pytest.mark.parametrize("face", list("URFDLB"))
def test_quarter_turns_have_order_four(face):
    assert Cube().apply(f"{face} {face} {face} {face}").is_solved()


@pytest.mark.parametrize("alg,order", [
    ("R U R' U'", 6),
    ("R U R' U R U2 R'", 6),
    ("F R U R' U' F'", 6),
    ("R' F R' B2 R F' R' B2 R2", 3),   # a corner 3-cycle
    ("R U' R U R U R U' R' U' R2", 3),  # an edge 3-cycle
])
def test_algorithm_orders(alg, order):
    cube = Cube()
    for _ in range(order):
        cube.apply(alg)
    assert cube.is_solved()


def test_face_turn_moves_the_right_stickers():
    """A U turn must send the front's top row to the left face."""
    facelets = Cube().apply("U").to_facelets()
    assert facelets[36:39] == [2, 2, 2]   # L top row now shows F's colour
    assert facelets[18:21] == [1, 1, 1]   # F top row now shows R's colour


def test_d_turn_is_consistent_between_corners_and_edges():
    """Regression: D's edge and corner cycles once ran in opposite directions."""
    facelets = Cube().apply("D").to_facelets()
    for face in (1, 2, 4, 5):
        bottom = facelets[face * 9 + 6:face * 9 + 9]
        assert len(set(bottom)) == 1, f"face {face} bottom row is {bottom}"


def test_every_slot_has_distinct_facelets():
    seen = set()
    for group in list(CORNER_FACELET) + list(EDGE_FACELET):
        for index in group:
            assert index not in seen
            seen.add(index)
    assert len(seen) == 48  # everything except the six centres


def test_facelet_roundtrip():
    rng = random.Random(1)
    for _ in range(300):
        cube = Cube().apply(random_scramble(25, rng))
        assert Cube.from_facelets(cube.to_facelets()) == cube


def test_from_facelets_rejects_nonsense():
    with pytest.raises(ValueError):
        Cube.from_facelets([0] * 54)
    with pytest.raises(ValueError):
        Cube.from_facelets([0] * 53)


def test_from_facelets_rejects_a_single_flipped_edge():
    facelets = Cube().to_facelets()
    a, b = EDGE_FACELET[0]
    facelets[a], facelets[b] = facelets[b], facelets[a]
    with pytest.raises(ValueError):
        Cube.from_facelets(facelets)


def test_invert_undoes():
    rng = random.Random(2)
    for _ in range(200):
        scramble = random_scramble(20, rng)
        assert Cube().apply(scramble).apply(invert(scramble)).is_solved()


def test_cancel_preserves_meaning():
    rng = random.Random(3)
    for _ in range(200):
        scramble = random_scramble(20, rng)
        assert Cube().apply(scramble) == Cube().apply(cancel(scramble))


@pytest.mark.parametrize("raw,expected", [
    ("R R", "R2"),
    ("R R'", ""),
    ("R2 R2", ""),
    ("R L R", "R2 L"),
    ("F F F", "F'"),
])
def test_cancel_shapes(raw, expected):
    assert " ".join(cancel(raw)) == expected


def test_rotate_alg_maps_side_faces_only():
    assert rotate_alg("R U R' U'", 1) == ["B", "U", "B'", "U'"]
    assert rotate_alg("R U R' U'", 4) == ["R", "U", "R'", "U'"]


def test_tokenize_handles_typography():
    assert tokenize("(R U R’ U’)") == ["R", "U", "R'", "U'"]


def test_format_move():
    assert format_move("R", 0) == ""
    assert format_move("R", 1) == "R"
    assert format_move("R", 2) == "R2"
    assert format_move("R", 3) == "R'"


def test_scramble_has_no_redundancy():
    rng = random.Random(4)
    for _ in range(200):
        moves = random_scramble(25, rng)
        faces = [m[0] for m in moves]
        for i in range(1, len(faces)):
            assert faces[i] != faces[i - 1]
        for i in range(2, len(faces)):
            if faces[i] == faces[i - 2]:
                assert {faces[i], faces[i - 1]} not in (
                    {"U", "D"}, {"R", "L"}, {"F", "B"})
