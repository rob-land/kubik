# Kubik — Quick start

Kubik teaches you to solve a Rubik's cube and times you once you can. It
works with no hardware at all; a Bluetooth smart cube adds automatic timing
and lets the lessons check your real cube instead of an on-screen one.

## Install

```sh
flatpak remote-add --user rob-land \
  https://rob-land.github.io/flatpak-repo/rob-land.flatpakrepo
flatpak install --user rob-land land.rob.kubik
```

## First time

Open **Learn** and start at the top. The course assumes nothing — the first
lesson is about which pieces exist and why the centres decide everything.

Hold the cube **white on the bottom, yellow on top** and keep it that way.
Every algorithm in the course is written for that grip, so re-orienting
mid-solve is the fastest way to get lost.

You do not need a cube that talks to the app. The **Play** tab has one you can
drag, turn and scramble, and every lesson works against it.

## Daily use

### Learn

Lessons are stacks of cards. Most are read-and-continue, but two kinds gate
you:

- **Quizzes** ask you to predict before the app tells you. A wrong answer
  explains what the reasoning missed rather than just saying no.
- **Your turn** cards watch the cube and only unlock once the goal state is
  actually reached. The grey squares in the goal picture are "don't care" —
  only the coloured ones have to match.

Stuck on one? **Show me the next move** names the step you are on and the
single next move, without solving it for you.

Switch between the 3×3 and 2×2 courses from the main menu. Progress is
tracked separately.

### Play

Drag to rotate, scroll to zoom, tap the move pad to turn. **Solve** produces a
layer-by-layer solution grouped into labelled steps; the play button on each
row replays just that step on the cube.

### Solve

For when you have a scrambled cube and no idea. Pick a colour, tap the
stickers on the unfolded net, and Kubik fills in whatever follows.

The six centres are there before you start. As you paint, the app rules out
what a real cube cannot be — no corner carries two whites, no colour appears
ten times, every piece exists exactly once — and any sticker left with only
one possibility is filled in for you. Those show a **small ring**, so you can
always tell what you entered from what was worked out.

Paint face by face and the effort tapers off sharply: the up and right faces
need all eight stickers, the left needs about three, and the back usually
needs none. Around 32 taps rather than 48.

Get one wrong and it says so immediately, naming the piece — "no real corner
has those colours (the URF corner)" — instead of a blanket "invalid" once you
have finished. **Clear** starts over; **Scan From Cube** loads whatever the
app currently believes, which is handy with a smart cube connected.

Hit **Solve** for the same explained, step-by-step solution the course
teaches. The entered cube is loaded into **Play** too, so you can step through
it in 3D.

### Timer

Press **Start**, or hit space. Averages of 5 and 12 follow the WCA rules — the
best and worst are dropped. Use **+2** and **DNF** on a row to penalise it,
and the bin to delete a misfire.

With a smart cube connected the timer runs itself:

1. Apply the displayed scramble to your cube.
2. The timer **arms** the moment the cube matches it.
3. It **starts** on your first solving turn.
4. It **stops** the instant the cube reads solved.

### Cubes

Turn a face to wake the cube's radio, then **Scan**. Connecting switches the
app to whichever puzzle the cube is (a GoCube 2×2 selects the 2×2 course).

The **Supported families** list is honest about what is decoded: some cubes
report their turns only, some also report absolute state, and GAN Gen3
connects but is not decoded yet.

## If a cube will not appear

- **Turn a face first.** Smart cubes sleep aggressively and stop advertising.
- Check Bluetooth is on. The app powers the adapter if it can.
- Some cubes advertise no service UUIDs, so they only appear once they are
  broadcasting — a scan started before you woke it will show nothing.

## Where things are kept

| What | Where |
|---|---|
| Solve history, course progress | `$XDG_DATA_HOME/kubik/solves.db` |
| Window size, selected puzzle | GSettings, `land.rob.kubik` |
| Log | `$XDG_DATA_HOME/kubik/kubik.log` |

Under Flatpak, `$XDG_DATA_HOME` is `~/.var/app/land.rob.kubik/data`.

Run with `--debug`, or set `KUBIK_DEBUG=1`, to log smart-cube packet traces.

## Notable limits

- The solver teaches the beginner method. It is not a speedcubing solver and
  will not produce a 20-move solution — that is deliberate, because an optimal
  solution cannot be explained.
- Only GAN Gen4 has been tested against real hardware. Other drivers are
  implemented and unit-tested but unproven; reports welcome.
- No account, no sync, no cloud. Your times stay on the device.
