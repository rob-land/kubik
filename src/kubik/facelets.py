"""Entering a cube by hand, with the impossible ruled out as you go.

Painting 54 stickers into a form and being told "invalid" at the end is a poor
deal: the mistake could be anywhere, and most of the work was never free to
begin with. A real cube constrains itself heavily.

* The six centres never move, so they are known before you start.
* Every corner is one of eight real pieces and every edge one of twelve, each
  appearing exactly once. Two colours of a corner narrow the third to two
  possibilities; knowing which pieces are already placed often narrows it to
  one.
* Each colour appears exactly nine times.
* Corner twists sum to zero mod three and edge flips sum to zero mod two, so
  the last piece of each kind is fully determined — identity *and*
  orientation.

`PartialCube` keeps only what you actually entered and re-derives everything
else after each edit, so a correction never leaves a stale deduction behind.
"""

from __future__ import annotations

from kubik.cube import (CORNER_COLOR, CORNER_FACELET, EDGE_COLOR,
                        EDGE_FACELET, Cube)

#: Facelet index of each face's centre, in URFDLB order.
CENTRES = tuple(face * 9 + 4 for face in range(6))

#: Every way a corner cubie can legally sit in a slot: the colours it puts on
#: the slot's three facelets, for each of the three twists. Reflections are
#: absent by construction — a physical cubie cannot be mirrored.
CORNER_PLACEMENTS = tuple(
    tuple(tuple(CORNER_COLOR[cubie][(position - twist) % 3]
                for position in range(3))
          for twist in range(3))
    for cubie in range(8)
)

EDGE_PLACEMENTS = tuple(
    tuple(tuple(EDGE_COLOR[cubie][(position - flip) % 2]
                for position in range(2))
          for flip in range(2))
    for cubie in range(12)
)


class Contradiction(Exception):
    """The stickers entered so far cannot belong to any real cube."""


class PartialCube:
    """A cube being entered by hand."""

    def __init__(self):
        self._user: dict[int, int] = {}
        self.facelets: list[int | None] = [None] * 54
        self.deduced: set[int] = set()
        self.problem: str | None = None
        self._recompute()

    # -- editing -----------------------------------------------------------

    def set(self, index: int, colour: int | None) -> None:
        """Paint one sticker. Centres are fixed and ignore this."""
        if index in CENTRES:
            return
        if colour is None:
            self._user.pop(index, None)
        else:
            self._user[index] = colour
        self._recompute()

    def clear(self) -> None:
        self._user.clear()
        self._recompute()

    @property
    def entered(self) -> int:
        return len(self._user)

    def is_user_set(self, index: int) -> bool:
        return index in self._user

    def remaining(self, colour: int) -> int:
        """How many stickers of a colour are still unplaced."""
        return 9 - sum(1 for value in self.facelets if value == colour)

    @property
    def complete(self) -> bool:
        return all(value is not None for value in self.facelets)

    # -- inference ---------------------------------------------------------

    def candidates(self, index: int) -> set[int]:
        """Colours that could still legally go on this sticker."""
        if index in CENTRES:
            return {self.facelets[index]}
        return self._candidates.get(index, set())

    def _recompute(self) -> None:
        self.facelets = [None] * 54
        for face, centre in enumerate(CENTRES):
            self.facelets[centre] = face
        for index, colour in self._user.items():
            self.facelets[index] = colour
        self.deduced = set()
        self.problem = None
        try:
            self._propagate()
        except Contradiction as err:
            self.problem = str(err)

    def _propagate(self) -> None:
        """Fill every sticker that only has one possible colour, repeatedly."""
        while True:
            self._candidates = self._compute_candidates()
            forced = [(index, next(iter(options)))
                      for index, options in self._candidates.items()
                      if len(options) == 1 and self.facelets[index] is None]
            if not forced:
                break
            for index, colour in forced:
                self.facelets[index] = colour
                self.deduced.add(index)

    def _compute_candidates(self) -> dict[int, set[int]]:
        corner_options = self._options(CORNER_FACELET, CORNER_PLACEMENTS)
        edge_options = self._options(EDGE_FACELET, EDGE_PLACEMENTS)
        self._prune_used(corner_options)
        self._prune_used(edge_options)
        self._prune_exhausted_colours(CORNER_FACELET, corner_options)
        self._prune_exhausted_colours(EDGE_FACELET, edge_options)
        self._apply_parity(corner_options, 3)
        self._apply_parity(edge_options, 2)

        candidates: dict[int, set[int]] = {}
        for table, options in ((CORNER_FACELET, corner_options),
                               (EDGE_FACELET, edge_options)):
            for slot, slot_options in enumerate(options):
                for position, index in enumerate(table[slot]):
                    candidates[index] = {
                        placements[orientation][position]
                        for _cubie, placements, orientation in slot_options
                    }
        return candidates

    def _options(self, table, placement_table):
        """Placements still consistent with the stickers already known."""
        options = []
        for slot, indices in enumerate(table):
            known = [(position, self.facelets[index])
                     for position, index in enumerate(indices)
                     if self.facelets[index] is not None]
            allowed = []
            for cubie, placements in enumerate(placement_table):
                for orientation, colours in enumerate(placements):
                    if all(colours[position] == colour
                           for position, colour in known):
                        allowed.append((cubie, placements, orientation))
            if not allowed:
                raise Contradiction(self._describe(table, slot))
            options.append(allowed)
        return options

    def _prune_used(self, options) -> None:
        """Match pieces to slots one-to-one.

        Two rules, alternated to a fixpoint. A slot with only one candidate
        piece claims it, removing it everywhere else; and a piece that fits
        only one slot must go there, even when that slot still looked open.
        The second rule is what makes entering the last face nearly free.
        """
        while True:
            changed = False

            claimed = {}
            for slot, slot_options in enumerate(options):
                cubies = {cubie for cubie, _, _ in slot_options}
                if len(cubies) == 1:
                    claimed[cubies.pop()] = slot
            for slot, slot_options in enumerate(options):
                kept = [option for option in slot_options
                        if claimed.get(option[0], slot) == slot]
                if len(kept) != len(slot_options):
                    if not kept:
                        raise Contradiction(
                            "two positions need the same piece")
                    options[slot] = kept
                    changed = True

            homes: dict[int, list[int]] = {}
            for slot, slot_options in enumerate(options):
                for cubie, _, _ in slot_options:
                    homes.setdefault(cubie, []).append(slot)
            if len(homes) < len(options):
                raise Contradiction("a piece of the cube is missing")
            for cubie, slots in homes.items():
                if len(set(slots)) != 1:
                    continue
                slot = slots[0]
                kept = [option for option in options[slot]
                        if option[0] == cubie]
                if len(kept) != len(options[slot]):
                    options[slot] = kept
                    changed = True

            if not changed:
                return

    def _prune_exhausted_colours(self, table, options) -> None:
        """A colour with all nine stickers placed cannot appear again."""
        counts = {colour: sum(1 for value in self.facelets if value == colour)
                  for colour in range(6)}
        full = {colour for colour, count in counts.items() if count >= 9}
        if not full:
            return
        for slot, indices in enumerate(table):
            free = [position for position, index in enumerate(indices)
                    if self.facelets[index] is None]
            if not free:
                continue
            kept = [option for option in options[slot]
                    if not any(option[1][option[2]][position] in full
                               for position in free)]
            if not kept:
                raise Contradiction(
                    "More than nine stickers of one colour")
            options[slot] = kept

    def _apply_parity(self, options, modulus: int) -> None:
        """The last piece's orientation is forced.

        Corner twists sum to zero mod three and edge flips to zero mod two, so
        once every other slot is pinned the remaining one has no freedom left.
        """
        undecided = [slot for slot, slot_options in enumerate(options)
                     if len({orientation for _, _, orientation in slot_options})
                     > 1]
        if len(undecided) != 1:
            return
        target = sum(slot_options[0][2]
                     for slot, slot_options in enumerate(options)
                     if slot != undecided[0]) % modulus
        wanted = (modulus - target) % modulus
        slot = undecided[0]
        kept = [option for option in options[slot] if option[2] == wanted]
        if kept:
            options[slot] = kept

    @staticmethod
    def _describe(table, slot: int) -> str:
        from kubik.cube import CORNERS, EDGES

        corner = table is CORNER_FACELET
        label = (CORNERS if corner else EDGES)[slot]
        kind = "corner" if corner else "edge"
        return f"No real {kind} has those colours (the {label} {kind})"

    # -- results -----------------------------------------------------------

    def status(self) -> tuple[bool, str]:
        """(ready to solve, a sentence describing where things stand)."""
        if self.problem:
            return False, self.problem + "."
        if not self.complete:
            missing = sum(1 for value in self.facelets if value is None)
            worked_out = len(self.deduced)
            extra = (f", {worked_out} worked out for you" if worked_out
                     else "")
            return False, (f"{54 - missing} of 54 stickers known{extra} — "
                           f"{missing} to go.")
        try:
            self.to_cube()
        except ValueError as err:
            return False, f"Not a solvable cube: {err}."
        return True, "Looks like a real cube. Ready to solve."

    def to_cube(self) -> Cube:
        if not self.complete:
            raise ValueError("some stickers are still unknown")
        return Cube.from_facelets([value for value in self.facelets])
