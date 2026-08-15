# Kubik — CLAUDE.md

## What this project is

A GTK4 + libadwaita app for learning to solve the Rubik's cube — 3×3 and 2×2 —
on GNOME and Phosh. It teaches the layer-by-layer method a step at a time,
checks progress against the cube itself, times solves, and talks to Bluetooth
smart cubes. Everything works without hardware; a connected cube is an
upgrade, never a requirement.

It began as a teardown of four commercial smart-cube apps (CubeStation,
GoCube, Rubik's Connected, GoCube 2×2). `docs/teardown.md` records what was
found and what was deliberately not copied — chiefly the account walls, the
stores and the battle passes.

## Code quality

Follow `STYLE_GUIDE.md` (dropped in from the cohort) and PEP 8. Files stay
short and single-purpose; a module accumulating unrelated concerns is a
structural smell, not a tradeoff.

## Before making changes

- Run the suite: `python3 -m pytest tests/ -q`. It is fast (~25 s) and covers
  the cube model, both solvers, every BLE decoder and a real UI drive.
- UI tests need the GResource bundle. `meson setup _build && meson compile -C
  _build` first, or they skip.
- Do not weaken a test to make it pass. The solver and protocol tests exist
  because each of them caught a real bug.

## Tech stack

- Python 3, PyGObject, GTK 4, libadwaita 1.
- Blueprint for the window shell, compiled to `.ui` and bundled via GResource.
- Meson + Ninja; Flatpak against `org.gnome.Platform//50`.
- SQLite (stdlib) for solve history and course progress.
- **No third-party Python dependencies.** BlueZ is spoken over Gio's D-Bus
  stack rather than `bleak`, and AES-128 is implemented in
  `src/kubik/ble/aes.py`, specifically so the Flatpak build needs no Rust
  toolchain and no `python3-deps.json`.

## Source layout

```
src/kubik/
  main.py            entry point; configures logging, then runs the app
  application.py     KubikApplication
  window.py          KubikWindow — the adaptive shell
  cube.py            Cube (3×3) and Cube2 (2×2): moves, facelets, notation
  solver/            layer-by-layer solver for both puzzles
  curriculum.py      lesson model; goal masks derived from solver stages
  facelets.py        PartialCube: hand entry with constraint propagation
  store.py           SQLite solve history and course progress
  logging_setup.py   configure_logging()
  ble/               aes, bluez transport, driver registry, per-vendor drivers
  views/             learn, play, solve, timer, cubes
  widgets/cube3d.py  Cairo-rendered cube and flat net
  widgets/neteditor.py  paintable net for hand entry
data/ui/             *.blp + gresource + style.css
tests/               pytest; fixtures in tests/data/
```

## Build workflow

```sh
meson setup _build && meson compile -C _build   # needed for UI tests
meson test -C _build                            # desktop, metainfo, schema, pytest
./build-all.sh --arch x86_64 --install          # flatpak
```

`build-all.sh` is the cohort-standard driver, with one local change: it skips
the `python3-deps.json` step entirely because `requirements.txt` lists no
packages.

## Key conventions

- **The first layer is D.** White on the bottom, yellow on top, which is how
  every beginner tutorial holds the cube. This makes every algorithm in the
  course the textbook one, so the lesson, the solver output and the hint all
  say `R U R' U'` for the right-hand algorithm. A test asserts they cannot
  drift apart — do not "fix" the frame without reading it.
- **Lesson goals are derived, not written.** A lesson names a solver stage;
  the picture the learner sees and the check that unlocks the next card both
  come from that stage's predicate. A lesson cannot disagree with the solver.
- **A 2×2 is a 3×3's corners.** `Cube2` shares the corner move tables and the
  solver reuses its three corner stages. Nothing is forked per puzzle; the
  renderer, curriculum and timer take a size.
- **Hand entry re-derives, never patches.** `PartialCube` stores only the
  stickers the user typed and recomputes every inference after each edit. A
  correction can therefore never leave a stale deduction behind. Do not be
  tempted to mutate the deduced set in place.
- **Moves are the primary channel from hardware**; absolute state is optional
  and used when a driver offers it. Sessions seed from an explicit "my cube is
  solved" sync, which is what makes a partially-understood protocol still
  useful.

## Things to watch out for

- **Smart-cube scans must not filter by service UUID.** A GAN i Carry 4
  advertises no UUIDs at all, so a filtered scan only finds cubes already in
  BlueZ's cache. Filtering happens in `identify()`, on the advertised name.
- **Order GAN packets by the cube's millisecond clock, not its serial.** The
  history a cube replays on connect carries serials that collide with turns
  still to come; the serial wraps inside a single session.
- **GAN Gen4 uses key index 0** — the Gen2 key/IV pair — and `fff6` notifies
  while `fff5` takes writes. Both contradict what is usually documented; both
  were confirmed against hardware.
- **A solved cube validates nothing about a state decoder.** Every
  self-consistent relabelling of faces, colours and sticker positions decodes
  solved as solved. Both GAN Gen4 and GoCube looked perfect on a solved cube
  and were wrong; only a scrambled capture with a known move sequence found
  it. Test state decoding against scrambled fixtures.
- **GoCube state is centre-first, then a clockwise ring** — not row-major —
  with U and D rotated a quarter turn in the net. Do not "simplify" it.
- **Do not send GoCube `0x35`.** It answers with a state message, but a run
  ending with it left the cube reporting solved while physically scrambled, so
  it plausibly resets the cube's tracking.
- GAN Gen4 and the Particula 3×3s have been tested against real cubes. GAN
  Gen2, Giiker and the GoCube 2×2 are tested up to the radio only.
- **Build D-Bus payloads from plain dicts, not nested Variants.**
  `GLib.Variant("(aya{sv})", (data, GLib.Variant("a{sv}", {...})))` raises
  `KeyError(0)`, which reaches the user as "Could not start the cube: 0". That
  shipped once and hid for weeks: notifications need no payload, so moves kept
  working while no driver could write at all. `tests/test_bluez.py` exercises
  the real transport with a recording bus — keep it that way rather than
  testing drivers only against fakes with their own `write`.
- **Every notification arrives twice**, byte-identical, within a millisecond,
  from every cube tried. The transport collapses repeats inside
  `DUPLICATE_WINDOW`; genuine turns of the same face were never closer than
  149 ms. Do not move this into a driver — it is BlueZ, not a vendor quirk.
- Don't block the GTK main loop. There is no worker thread here by design —
  BlueZ is GLib-native, so callbacks already arrive on the main loop.
