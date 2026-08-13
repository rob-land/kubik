# Kubik

A cube-solving tutor for GNOME desktop and Linux Mobile. Teaches the
layer-by-layer method for the 3×3 and the 2×2, times your solves, and talks to
Bluetooth smart cubes — but works just as well with a cardboard one.

---

## What it does

**Learn** — two courses: twelve lessons for the 3×3, from "the centres never
move" to a full solve, and six for the 2×2. Switch puzzle from the main menu;
progress, scrambles and statistics all follow.

Each lesson is a stack of cards: explanation, algorithm demos you can play on
an on-screen cube, quizzes that ask you to predict before being told, and a
*do it* card that watches the actual cube and will not let you continue until
the goal state is genuinely reached. Wrong quiz answers get a specific
correction ("check the centre pieces"), not "try again".

**Play** — a drag-rotatable cube, a move pad, a scrambler, and a
layer-by-layer solver that shows its work: every step is labelled with the
stage it belongs to and what it achieves, and each can be replayed on the
cube.

**Solve** — got a scrambled cube and no idea? Paint its colours onto an
unfolded net and Kubik works out the rest. It knows the six centres before you
start, knows every corner and edge is one of a fixed set of real pieces, knows
each colour appears nine times, and knows the last piece's orientation is
forced by parity — so it fills in what follows from what you have typed and
tells you precisely which sticker is impossible when you slip. In practice you
paint four faces and the last two mostly complete themselves: about 32 entries
instead of 48. Then it hands you the same explained, step-by-step solution the
course teaches.

**Timer** — WCA-style averages of 5 and 12, best time, +2/DNF penalties and
history, kept separately per puzzle. With a smart cube connected it runs
itself: it arms when the cube matches the displayed scramble, starts on your
first solving turn, and stops the instant the cube reads solved.

**Cubes** — scanning and connection, and an honest list of which families are
fully decoded.

Everything is local. No account, no network access, no store.

## Smart cube support

| Family | Products | Status |
|---|---|---|
| GAN Gen4 | GAN12 ui Maglev, GAN14 ui, i carry E / 4, GAN12 ui SP, GAN 251 | Moves, state, battery — **verified on hardware** |
| GAN Gen2 | GAN356 i / i2 / i Play / i3, GAN12 ui, GAN mini ui FreePlay, GAN i carry S | Moves, state, battery, hardware |
| GoCube / Rubik's Connected | GoCube, GoCube Edge, Rubik's Connected | Moves, state, battery |
| GoCube 2×2 | GoCube 2×2 | Moves, state, battery |
| Giiker | Giiker i3, Xiaomi Mi Smart Magic Cube | Moves |
| GAN Gen3 | GAN i carry 2 | Detected and connects; packet format not decoded |

GAN Gen4 was reverse engineered against a real GAN i Carry 4; two captures
from it ship as test fixtures, including a 254-turn session that starts and
ends solved. The other drivers have not met their hardware — they are tested
up to the radio and may need a fix on first contact. See
[`docs/teardown.md`](docs/teardown.md).

## Tech stack

- **Language**: Python 3.10+
- **UI toolkit**: GTK 4 + libadwaita 1 (PyGObject), Blueprint templates
- **Bluetooth**: BlueZ over Gio's D-Bus stack — no `bleak`, no worker thread
- **Storage**: GSettings (window geometry, selected puzzle), SQLite
  (solve history, course progress) at `$XDG_DATA_HOME/kubik/solves.db`
- **App ID**: `land.rob.kubik`
- **License**: GPL-3.0-or-later
- **Third-party Python dependencies**: none

## Install

```sh
flatpak remote-add --user rob-land \
  https://rob-land.github.io/flatpak-repo/rob-land.flatpakrepo
flatpak install --user rob-land land.rob.kubik
```

## Build

```sh
meson setup _build
meson compile -C _build
meson test -C _build
```

Flatpak bundles for both arches:

```sh
./build-all.sh --arch x86_64 --install
```

## Layout

```
data/           desktop entry, metainfo, gschema, icons, Blueprint UI
docs/           quickstart, teardown notes
src/kubik/      the application package (ble/, views/, widgets/)
tests/          pytest suite, with hardware captures in tests/data/
```

## Tests

```sh
python3 -m pytest tests/ -q
```

182 tests. Both solvers are checked against several hundred random scrambles
per run plus known-awkward states; the Gen4 driver is replayed against two
real hardware captures; and the UI tests build the real window and drive it —
switching pages and puzzles, walking every lesson card in both courses,
scrambling, solving, and running a full smart-cube timer cycle. UI tests skip
unless `meson compile` has produced the GResource bundle.

## License

GPL-3.0-or-later — see [COPYING](COPYING).
