# Kubik — design notes

The "why" behind the pedagogy and the architecture. Implementation detail
lives in the code; this is the reasoning that is not obvious from reading it.

---

## Where the pedagogy came from

Kubik started as a teardown of four commercial smart-cube apps. The full
findings are in [`docs/teardown.md`](docs/teardown.md); what mattered for the
design was that both vendors had independently converged on the same core
idea, and both had buried it.

**GoCube's `Particula.Learn` is a condition interpreter over live cube state**,
not a video player. It carries typed conditions — `ConditionCubeState`,
`ConditionMatchingFaces`, `ConditionSelectionInPlace`,
`ConditionYellowLayerRotationDirection` — plus a `CubeOrientationChecker` that
verifies the learner is *holding the cube correctly* before a step begins. Its
audio layer has a `badMoveAudioClip`: wrong turns get immediate non-verbal
feedback, because the learner's eyes are on the cube, not the screen.

**CubeStation's lesson engine is one data structure**: a 54-entry facelet mask
where `-1` means "don't care" and `0..5` is a required colour, plus the
orientation the cube must be held in. Entry conditions, success conditions,
quiz diagrams and algorithm recognition all use that single representation.
Its tip counts are the interesting part — 20 tips on step 1, **92 on "Base
Corners"** — which is a direct measurement of where learners get stuck.

Three devices were worth taking:

- **Quiz before algorithm.** Almost every GoCube step asks the learner to
  predict before telling them what to do, and a wrong answer gets a *specific*
  correction ("check the centre pieces"), never "try again".
- **Orientation gates.** Hints are expressed relative to the hands, not the
  model. CubeStation stores `move` and `moveUpFront` separately for exactly
  this reason: the same physical turn has a different name depending on grip.
- **Daisy first.** Both teach the white cross via the daisy, because it is
  measurably easier than building the cross directly.

And what not to take: both apps hard-require an account and a physical cube to
get past first launch (`First_login_requires_a_GoCube`), and bury the course
under a store, a battle pass and ranked multiplayer.

## Three decisions that shaped the code

### The first layer is D

White on the bottom, yellow on top — how every beginner tutorial holds the
cube. This looks like a trivial convention choice and is not.

The first implementation put white on U, which meant the last layer was D,
which meant every textbook algorithm had to be mirrored through a `z2`
relabelling. The lesson would have taught `R U R' U'` while the solver emitted
`F D F' D'`. Flipping the frame deleted the mirror entirely, and a test now
asserts the taught algorithms are character-for-character what the solver
emits and what the hint button says.

### Lesson goals are derived, not written

A lesson names a solver stage (`cross`, `ll-corners-permute`). The goal
picture the learner sees and the check that unlocks the next card are both
generated from that stage's predicate. A lesson therefore *cannot* disagree
with the solver about what "white cross" means — the class of bug where the
tutorial and the checker drift apart is unrepresentable.

### A 2×2 is a 3×3's corners

`Cube2` shares the corner move tables, and the 2×2 solver reuses the same
three corner stages the 3×3 uses: first layer via the right-hand algorithm,
orientation via Sune, permutation via the A-perm. The renderer, curriculum
engine and timer take a size rather than forking.

The first attempt at this was wrong in an instructive way: I assumed a 2×2
could be packed as "a 3×3 with edges pinned solved" and reuse `solve()`
untouched. It failed 311 of 600 scrambles, because the corner insertions churn
the edges, so the pinned edges become fiction and the solver chases them into
unsolvable states. The fix was corner-only predicates, not a pinned state.

The usual worry about a 2×2 — no centres, so "solved" needs a reference — does
not arise. The frame is the cube's own body, which is what a smart cube
reports against and what the on-screen cube displays.

## Hand entry: rule out the impossible as you go

The web solvers hand you 54 blank stickers, let you paint all of them, and
then say "invalid". Both halves of that are worse than they need to be. The
mistake could be anywhere, and most of the painting was never free to begin
with — a real cube is heavily constrained:

- The six centres never move, so they are known before you start.
- Every corner is one of eight real pieces and every edge one of twelve, each
  appearing exactly once. Two colours of a corner *in known positions* pin the
  piece uniquely, so the third sticker is free.
- Each colour appears exactly nine times.
- Corner twists sum to zero mod three and edge flips to zero mod two, so the
  last piece of each kind is determined — identity *and* orientation.

`PartialCube` maintains, per slot, the set of (piece, orientation) placements
still consistent with what is known, prunes it by piece uniqueness in both
directions (a slot that can only hold one piece claims it; a piece that fits
only one slot is placed there), by exhausted colours, and by parity — then
fills any sticker whose surviving placements all agree. Repeat to a fixpoint.

Entering face by face, that costs about 32 entries instead of 48. The saving
is not evenly spread, which is the nice part: U and R need all eight, F needs
seven, D about six, L about three, and B under one. The work tapers to nothing
exactly when hand-entering is most tedious.

Errors are localised rather than deferred: painting a second white onto a
corner is rejected the moment it happens, naming the corner, instead of
surfacing as a generic "invalid" forty stickers later.

## Why the solver is layer-by-layer

CubeStation ships two solvers: a Kociemba two-phase `cs::Search` and a
separate `cs::HumanSolverLBL`. That split is the whole argument. A 20-move
two-phase solution is optimal and unexplainable; it cannot teach. Kubik's
solver produces ~126 moves for a 3×3 and ~48 for a 2×2 — squarely in the
normal beginner band — and every step carries the stage it belongs to and what
it achieves.

Output is run through a cancellation pass (`R R` → `R2`, `R R'` → nothing)
before display, mirroring CubeStation's `mergeRepetedFormula`.

## Smart cubes: moves are the contract

Drivers are only required to emit **moves**. Absolute state is optional.

Every supported cube reports its turns reliably; the encodings for absolute
state vary far more, and one generation's is still undecoded. Making moves the
contract means a partially-understood protocol is still fully useful: the
session seeds its model from an explicit "my cube is solved" sync — which is
what GoCube's own app does (`Cube must be in a solved state to start`) — and
tracks from there.

Bluetooth is spoken to BlueZ over Gio's D-Bus stack rather than `bleak`. That
keeps everything on the GLib main loop with no asyncio bridge and no worker
thread, and it is the reason the app has no third-party Python dependencies at
all. AES-128 for the GAN cubes is implemented in-tree for the same reason: a
Rust toolchain in the Flatpak build sandbox is a steep price for one block
cipher over 20-byte packets.

## Two bugs that hid each other

Worth recording as a pair, because neither was findable without the other
being fixed first.

`Peripheral.write` built its D-Bus payload by wrapping the options dict in a
`GLib.Variant` and then wrapping that again. PyGObject raises `KeyError(0)`
while unpacking the outer tuple, and `str(KeyError(0))` is `"0"` — so the app
said "Could not start the cube: 0" and pointed nowhere. **No driver could
write to any cube.** It hid because reading a notification needs no payload,
so the move stream worked perfectly, and because every hardware harness had
its own `write`: the drivers were only ever tested against fakes.

Underneath it sat a second defect. Every BLE notification arrives **twice**,
byte-identical, within a millisecond — from a GAN i Carry 4 and a Rubik's
Connected X alike, so it is BlueZ rather than any vendor. The driver emitted
two moves per turn, which would have double-applied every turn to the model.
The write bug masked it entirely: `start()` threw before subscribing, so in
the app no moves ever arrived.

The fix was decided by measurement rather than taste. Across a real session,
identical consecutive frames were 0–1 ms apart, and genuinely different frames
were never closer than 149 ms. A 25 ms window sits 25x above the duplicates
and 6x below the fastest real turn, and it lives in the transport because both
vendors show the behaviour. Confirmed on hardware: six turns produced six
moves, including two consecutive `R` turns that both survived.

## What hardware changed

GAN Gen4 was decoded against a real GAN i Carry 4. Four things were wrong
beforehand that no amount of static analysis would have caught, and they are
worth remembering as a class:

1. `fff6` notifies and `fff5` takes writes — the reverse of the assumption.
2. The cipher uses key index 0, the *Gen2* key pair, not the index 1
   documented for that generation.
3. Packets must be ordered by the cube's millisecond clock, not its serial:
   the history replayed on connect carries serials that collide with turns
   still to come, because the serial wraps inside a session.
4. The cube advertises **no service UUIDs at all**, so a UUID-filtered scan
   only ever finds cubes already in BlueZ's cache.

The last one is the reason `Central.start_discovery` deliberately does not
filter, and matching happens on the advertised name instead.

The Rubik's Connected X repeated the lesson in a different costume. Everything
reconstructed from the IL2CPP metadata was right first time — the UUIDs, the
`0x2A`/length/type/payload/checksum/CRLF framing, the checksum formula, the
`B F U D R L` move codes with the low bit for anticlockwise. Fifty-two
recorded turns replayed a model cube back to solved on the first attempt.

What was wrong was the one thing the metadata only named rather than valued:
the state message's sticker order. It is **centre first, then the eight ring
stickers clockwise**, with U and D rotated a quarter turn once flattened into
the net — not the row-major order the net is drawn in.

Two solved-cube readings had already looked perfect and told me nothing, which
is the general lesson: **a solved cube cannot validate a state decoder**, since
every self-consistent relabelling of faces, colours and positions decodes
solved as solved. The bug only surfaced on a scrambled cube, and was confirmed
by reading the state, watching 62 turns, reading again, and checking the two
agreed.

The command bytes were guesses too, and two of three were wrong: `0x33` reads
state and `0x32` reads battery, the reverse of the assumption. `0x35` also
answers with a state message but is no longer sent — the run that ended with it
left the cube reporting solved while physically scrambled, so it plausibly
resets the cube's tracking, and nothing here needs it.
