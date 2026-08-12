# Smart-cube app teardown

Reverse-engineering notes on four commercial smart-cube Android apps, written to
inform the design of Kubik. The XAPKs themselves are not in this repository.

| App | Package | Version | Engine | Size |
|---|---|---|---|---|
| CubeStation | `com.gan.cubestation` | 6.6 | Tuanjie (Unity China) 2022.3.48t6, IL2CPP + embedded Vue/Vite WebView | 346 MB |
| GoCube™ | `com.particula.gocube` | 6.1 | Unity IL2CPP (metadata v31) | 219 MB |
| Rubik's Connected | `com.particula.rubiksconnected` | 2.5 | Unity IL2CPP (metadata v31) | 218 MB |
| GoCube2x2™ | `com.particula.gocube2x2` | 2.2 | Unity IL2CPP (metadata v31) | 151 MB |

## Method

No jadx/Il2CppDumper was needed for the parts that mattered.

* XAPK → APK splits → `unzip`.
* Particula apps: wrote `il2cpp_strings.py`, which reads the `global-metadata.dat` header
  (`sanity`/`version`/`stringLiteral*`/`string*` offsets are stable from metadata v24 through v31)
  and dumps the literal table and the identifier blob as discrete strings. Recovered ~92 k
  identifiers and ~18 k literals per app — enough to reconstruct namespaces, class layouts and
  BLE constants.
* Unity assets: `UnityPy` over `data.unity3d` and the YooAsset bundles → `TextAsset` extraction.
* CubeStation: its `global-metadata.dat` is fully encrypted (sanity reads `0x3C817E22`, not
  `0xFAB11BAF`), so IL2CPP was a dead end — but the app ships its logic in three *unencrypted*
  places instead: a Vue/Vite web bundle, a C++ solver library with intact symbols, and 79 JSON
  data bundles.

The working tree of the teardown lives outside this repository.

---

## 1. Rubik's Connected == GoCube, re-skinned

`German.txt` (and every other localization asset) is **byte-identical** between
`com.particula.gocube` and `com.particula.rubiksconnected`. Same 566 keys, same engine, same
`Particula.*` namespaces, same firmware blobs. The only divergence is branding strings that live
side by side in the same file:

```
Lets_start_with_a_solo_run_How_quick_can_you_solve_GoCube
Lets_start_with_a_solo_run_How_quick_can_you_solve_Rubiks
First_login_requires_a_GoCube_Please_try_again_or_get_yours_at_wwwGetGoCubecom
First_login_requires_a_Rubiks_Please_try_again_or_get_yours_at_wwwRubikscom
```

GoCube2x2 is the same codebase again, carrying the *entire* 3×3 curriculum as dead weight plus 41
`Learn2x2_*` keys layered on top.

**Both apps hard-require a physical cube and an account to get past first launch**
(`First_login_requires_a_GoCube`). That is the single biggest thing to not copy.

## 2. Bluetooth: what each app actually speaks

### 2.1 Particula family (GoCube / Rubik's Connected / GoCube 2×2)

UUID literals recovered from `global-metadata.dat`:

| UUID | Role |
|---|---|
| `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` | Nordic UART Service — the GoCube transport |
| `6E400002-…DCCA9E` | NUS RX (host → cube, commands) |
| `6E400003-…DCCA9E` | NUS TX (cube → host, notifications) |
| `0000aadb-0000-1000-8000-00805f9b34fb` | Giiker service (Xiaomi Mi Smart Magic Cube) |
| `0000aadc-…` | Giiker state characteristic |
| `0000aaaa-…` / `0000aaac-…` | Giiker secondary/OTA |
| `0000180a-…` + `2a24/2a26/2a28/2a29` | Device Information (model, firmware rev, software rev, manufacturer) |
| `F0000000-0451-4000-B000-000000000000` | TI OAD — over-the-air firmware update |
| `00002902-…` | CCCD |

So a single Particula binary drives **two unrelated cube families**: its own GoCube hardware over
NUS, and Giiker cubes. The identifier blob confirms it — `GoCubeParser` holds an `isGiiker` flag
and delegates to `CubeGiikerMsgParser.ParseMsgGiiker` via `ParseGiikerContent`.

`GoCubeParser`'s recovered members give the whole framing scheme and message set:

```
PrefixLength  SuffixLength  ChecksumLength
FirstLetter   PreLastLetter LastLetter      MinimumConstantLettersInMsgLength
msgStartIndex msgLength     ParseContents   SubArray

ParseMsgRotatingSide            → RotatingSide
ParseMsgCubeColorAndDirectionState → CubeColorAndDirectionState
ParseMsgQuaternion / ParseMsgQuaternionShort → Quaternion, QuaternionShort
ParseMsgBatteryLevel            → BatteryLevel
ParseMsgOfflineStats            → OfflineStats
ParseMsgIsEdgeCube              → (GoCube Edge detection)
ParseMsgCubeInfo                → CubeInfo, CubeType
```

i.e. `<prefix><len><type><payload><checksum><suffix>`, with the suffix being a two-byte
`PreLastLetter`/`LastLetter` pair — CRLF. Concrete byte values are `const` fields, which live in
the metadata's default-value region that this dump does not decode; the driver in `kubik/` uses
the public GoCube framing (`0x2A` prefix, `0x0D 0x0A` suffix) which matches the recovered
structure exactly.

Other confirmed details: the cube reports its model through `Cube type = 0x35, new Code IMU270`,
an IMU that can be disabled (`Disable_IMU` / `Enable_IMU`) and needs periodic recalibration
(`ReCalibrating_IMU`, `Place_your_cube_on_a_flat_surface_with_the_orange_center_on_top`), and
`GoCubeXFW_EE_EF` / `GoCubeFW_V25_DFU 1` firmware images shipped inside the APK.

### 2.2 CubeStation (GAN)

CubeStation carries 21 encrypted protocol descriptors in `assets/`:

```
GanSDK_Protocol.alpha            GanSDK_ProtocolLogic.alpha       GanSDK_ProtocolLogicWrite.alpha
GanSDK_ProtocolV1/V2/V3/V3-2     GanSDK_ProtocolWriteV1/V2/V3
GanSDK_ProtocolRobotV1/V2        GanSDK_ProtocolRobotWriteV1/V2
GanSDK_ProtocolTimerV1/V2        GanSDK_ProtocolTimerWriteV1V2
GanSDK_ProtocolWislideV1/V2      GanSDK_ProtocolWislideWriteV1/V2
```

Base64 over AES-**ECB** (1215 blocks, only 440 distinct; `WislideV1` and `WislideV2` are
byte-identical; all read-side files share the same first ciphertext block, all write-side files
share a different one). The key is not a plain byte array anywhere in the APK — the four
well-known GAN Gen2/Gen3/Gen4 key+IV constants do not appear — and the C# that would hold it is
behind the encrypted IL2CPP metadata. Not decrypted.

It did not matter, because **the same protocol is implemented in readable JavaScript** in the
bundled WebView app (`assets/assets/index-757c40c0.js`, a Vue 3 + Pinia SPA). `LogicCubeParse`
is a straight bit-field reader, and it decodes to the GAN Gen2 layout:

| Type | Bit-field sequence (width × count) | Meaning |
|---|---|---|
| 1 | `1,15 ×4` then `1,3 ×3` | GYRO — quaternion (sign + 15-bit magnitude × 4), angular velocity × 3 |
| 2 | `8`, `5 ×7`, `16 ×7`, `1` | MOVES — serial, 7 move codes, 7 inter-move times |
| 4 | `8`, `3 ×7`, `2 ×7`, `4 ×11`, `1 ×11`, `9 ×3` | FACELETS — serial, CP, CO, EP, EO |
| 5 | `4`, `8 ×4`, `8 ×8`, `1`, `1` | HARDWARE — hw/sw version, device name, gyro flag |
| 9 | `4`, `8` | BATTERY |
| 13 | `1` | DISCONNECT |

and the app wires them up exactly that way:

```js
const c = [{ address: "",
  serviceName:        "6e400001-b5a3-f393-e0a9-e50e24dc4179",
  characteristicName: "28be4cb6-cd67-11e9-a32f-2a2ae2dbcce4",
  descriptorUUID:     "00002902-0000-1000-8000-00805f9b34fb" }];
…
if (C == 2) { t.onMove(P); … }      // moves
if (C == 4) { n.cubeOnSync(P); … }  // facelets
C == 5 && t.BleReceiveCubeInfo(P);  // hardware
C == 9 && t.onBattery(P);           // battery
```

(That particular bundle is the 小天才 / imoo kids-watch build — it has `xtcLoginByCode` — which is
why it hard-codes one protocol instead of using the `.alpha` table.)

**The device table is shipped in the clear.** `devicedata_cn.json`, 32 entries, maps every GAN
product to its protocol generation, gyro capability and OTA type:

| proto | Devices |
|---|---|
| 1 | GAN356 i / i2 / i Play / i Play 2 / i3, GAN12 ui, GAN12 ui FreePlay, GAN mini ui FreePlay, GAN i carry S, GAN ROBOT, GAN Timer, XES, MG3 AI |
| 2 | GAN i carry 2 (`GANicV2S`) |
| 3 | GAN12 ui Maglev, GAN14 ui, GAN i carry E / E2, GAN12 ui SP, GAN i3 v2, GAN i4, GAN i carry 4, GANic251, GAN251ui, GAN00 |

Note GAN's internal numbering (`proto` 1/2/3 ↔ `ProtocolV1/V2/V3`) is **offset by one** from the
community's Gen2/Gen3/Gen4 naming. `blenamedata_cn.json` gives the advertised-name prefixes used
for scan filtering (`GANicE2_`, `GAN12uiFp2-`, `GAN12i_`, `GAN14ui_`, `GANi3V2_`, `GANi4v2_`,
`GAN12uiM2_`, …), each with a `connect` and a `changeName` capability flag.

The app also speaks to a **GAN Robot** and a **GAN Smart Timer** over the same SDK — worth
knowing, though out of scope for a first release.

### 2.3 GAN Gen4, from hardware

The `.alpha` blobs were never cracked, but a GAN i Carry 4 (`GANic4`, `proto: 3`)
made them unnecessary. Captured over BlueZ and decrypted with the scheme above,
the plaintext is a run of type/length/value records inside the 20-byte frame:

```
01 07  <u32le ms> <u16le serial> <move>     a turn
02 04  <u32le ms>                           that turn completed
ED 0E  <u16le serial> <12 bytes>            the cube state after that turn
EF 01  <percent>                            battery, sent periodically
3A 00                                       end of list
```

A **move byte** is a one-hot face in bits 0-5 — `F B U D R L` — with bit 6 set
for anticlockwise.

The **state body** is 7x3 corner slots, 8x2 corner twists, 11x4 edge slots,
12x1 edge flips, three spare bits: 93 of 96. The eighth corner and twelfth edge
come back by elimination. GAN numbers slots and pieces differently from URFDLB
and measures twist against its own reference sticker, so decoding also needs
three relabelling tables and a per-piece orientation offset; the slots fall into
two classes whose references differ by one further step.

Three details contradict what is usually documented for this generation, and
all three were wrong in this app until the cube said otherwise:

* `fff6` notifies and `fff5` takes writes, not the reverse.
* The cipher uses **key index 0** — the Gen2 key/IV pair — not index 1.
* The cube **advertises no service UUIDs at all**, so scanning with a UUID
  filter never finds one that BlueZ has not already cached.

Ordering has to be done on the cube's millisecond clock rather than its serial:
the history it replays on connect carries serials that collide with turns still
to come, because the serial wraps well inside a single session.

Validation, on 254 turns from a cube that started and finished solved: the
decoded move stream returns a model cube to solved; all 611 reported states
decode to legal cubes; and the states the cube reports agree with the states
implied by the moves it reported making, at every step. A second capture from a
different day and a different starting state decodes with the same tables.

### 2.4 Coverage matrix

| Cube family | GoCube | Rubik's Connected | GoCube 2×2 | CubeStation |
|---|---|---|---|---|
| GoCube (NUS) | ✅ | ✅ | ✅ | — |
| Giiker | ✅ | ✅ | ✅ | — |
| GAN proto 1 (Gen2) | — | — | — | ✅ |
| GAN proto 2 (Gen3) | — | — | — | ✅ |
| GAN proto 3 (Gen4) | — | — | — | ✅ |
| GAN Robot / Timer | — | — | — | ✅ |

Nobody covers everything. **That gap is the reason this project exists.**

## 3. Solvers

### CubeStation — `libcs.so` (710 KB, C++ symbols intact)

Namespace `cs::`, and the symbol table reads like a table of contents:

```
cs::CubieCube  cs::AxisCube  cs::AxisCubieCube  cs::ColorCube  cs::FaceCube
cs::CoordCube  cs::CoordCubeTables  cs::pruning_table<>  cs::Search        ← Kociemba two-phase
cs::HumanSolver
cs::HumanSolverLBL   solveDCross → solveDLayer → solveMLayer → solveUCross
                     → solveUFace → solveUCorner → solveFinal
cs::HumanSolverCFOP  solveCross → _solveF2L_internal → OLL → PLL
```

plus predicates the teaching UI polls every state update:
`isDCrossSolved`, `isDLayerSolved`, `isF2LSolved`, `numPairF2LSolved`, `numPairF2LIgnoreDCross`,
`isOLLSolved`, `isUCrossSolved`, `isOnlyUEdgeOriSolved`, `isOnlyUCornerPermSolved`, …

and formula post-processing: `mergeRepetedFormula`, `formula_append_merge`,
`formula_append_merge_rot`, `mergeRepetedRotateFormula` — i.e. the raw solver output is
**cancelled and rotation-merged before being shown to the learner**. That is a detail worth
stealing: `R R` → `R2`, `R R'` → nothing, and whole-cube rotations folded away.

### Particula — Kociemba two-phase, shipped as pruning tables

The `TextAsset` list is literally Kociemba's table set:
`twist_move`, `flip_move`, `slice_twist_prun`, `slice_flip_prun`, `ur_to_df_move` (2.0 MB),
`urf_to_dlf_move` (1.9 MB), `fr_to_br_move`, `ub_to_df_move`, `ur_to_ul_move`, `merge_move`,
`slice_urf_to_dlf_prun`, `slice_ur_to_df_prun` — ~8 MB of precomputed tables. The C# side is
`RubiksCubeLib` (`RubiksCubeLib.Solver`, `RubiksCubeLib.CubeModel`, `RubiksCubeLib.ScanInput`).

Two-phase gives short solutions but **unreadable ones** — which is why GoCube's *teaching* mode
does not use it, and CubeStation ships a separate `HumanSolver`. A learning app needs the human
solver as the primary and the optimal solver only as "just solve it".

## 4. Pedagogy — the actually valuable part

### 4.1 GoCube: a condition-driven tutorial state machine

`Particula.Learn` is not a video player with a next button. It is an interpreter over typed
conditions evaluated against live cube state:

```
Condition            ConditionNot          ConditionNumerical (Greater/Less/GreaterOrEquals/…)
ConditionColors      ConditionCubeState    ConditionMatchingFaces
ConditionProgress    ConditionSelection    ConditionSelectionEqual
ConditionSelectionInPlace                  ConditionSelectionSharedColor
ConditionSelectionEdgePositionSide         ConditionYellowLayerRotationDirection
```

with a `CubeStatesChecker` over a named state enum, and a `CubeOrientationChecker` that verifies
the learner is *holding the cube the right way* before a step begins
(`CheckTopOrientation`, `CheckFrontOrientation`, `PieceInFront`, `PieceOnTop`, with a `THRESHOLD`):

```
Scrambled  StrongScrambled  Daisy  WhiteCross  WhiteFaceSolved  WhiteAndMiddleLayersSolved
YellowCross  YellowLine  YellowHalfCross  YellowCrossAndCorners
YellowCrossCornersRotatedCorrectly
YellowHalfCross1_ORANGE_BLUE  YellowHalfCross2_BLUE_RED
YellowHalfCross3_RED_GREEN    YellowHalfCross4_GREEN_ORANGE
YellowLine1_GREEN_BLUE        YellowLine2_RED_ORANGE
```

Note that the yellow-cross cases are enumerated *with their specific colour pairs*, not just as
shapes — so the app can tell you exactly how to rotate before the algorithm, rather than saying
"orient it correctly".

There is an `IAudioBroadcaster` / `TutorializerAudio` layer with `progressAudioClips`,
`successAudioClip`, **`badMoveAudioClip`** and `solveAudioClip`. Wrong turns get immediate
non-verbal feedback. The very first lesson step is `Learn_Sound_on_Text` — "make sure your sound
is on" — because the audio channel is load-bearing when the learner's eyes are on the cube.

The 357 `Learn_*` keys spell out the course:

0. **Basics** — centres never move; face-colour quiz; opposite-face quiz; layers; edges (count
   quiz, which-colours quiz, which-edge-fits quiz); corners (count quiz, which-corner-fits quiz).
1. **Notation** — R L U D F B, then primes, then doubles, then practice strings
   (`RUF`, `LULU`, `FRURUF'`, `L'RFF`), then `R U R' U'` drilled by name as
   *"the right-hand algorithm"*.
2. **White cross** — via **Daisy** first (`Looking_Fresh_As_A_Daisy`), edge by named colour:
   green-white → red-white → blue-white, each `MatchFace` then `F2`.
3. **White corners** — right-hand algorithm repeated; quizzes on where a corner belongs.
4. **Middle layer** — right-hand and left-hand algorithms, with a *which side does this edge go*
   quiz before each.
5. **Yellow cross** — dot / line / half-cross quiz, then per-case orientation instructions.
6. **Yellow corners** — position first (right-hand ×3, rotate, left-hand ×3).
7. **Yellow face** — twist corners with repeated right-hand, `D` to the next corner.
8. **Final** — last-layer edges, with a clockwise/counter-clockwise quiz.
9. **Free solve / Library** — practice mode plus a tip library indexed per step.

Three recurring devices:

* **Quiz before algorithm.** Almost every step asks the learner to *predict* before it tells them
  what to do (`Learn_WhichCornerShouldFitQuiz`, `Learn_Quiz_Would_This_Piece_Go_On_The_Left_Side_Or_On_The_Right_Side`).
  Wrong answers get a *specific* correction, not "try again":
  `Learn_Wrong_Text_Not_Check_The_Center_Pieces`,
  `Learn_Wrong_You_Can_Tell_The_Right_Location_Of_A_Piece_ByThe_Center_Pieces`.
* **Explicit orientation gates.** `Learn_Orientation_Hold_Your_Cube_So_The_Yellow_Face_Is_Facing_Up_And_The_Red_Is_Facing_You`
  before every algorithm, checked against the IMU.
* **Progress-bar conditions.** `Learn_CenterStaysSame_Info_Progress_Bar_Text_Template: "%PROGRESS drehen"` —
  "turn the cube N more times" as a satisfiable goal, so exploration is a step, not a detour.

### 4.2 CubeStation: data-driven lessons with facelet masks

Same idea, different and better-factored data model. `lesson_lbllessons.json`:

```json
{ "lesson": 1, "phase": 1, "name": "White Petals",
  "desc": "Yellow center piece facing up, finish 4 white edges to make white petals.",
  "tips": [101, …, 120],
  "scramble": "F R U B' L B' L R'",
  "upFront": [3, 2],
  "state":    [ -1, -1, -1, -1, 0, … ],
  "stateEnd": [ -1, -1, -1, -1, 0, … ],
  "stateEndMove": "R2 F2 L2 B2" }
```

The whole engine is: a **54-entry facelet mask** where `-1` means *don't care* and `0..5` is a
required colour, plus `upFront` (which two centres must face up and front). Entry condition,
success condition, quiz diagrams (`lesson_questiondata.json`), transitions
(`lesson_transitiondata.json`) and summaries all use that one representation. 20 tips attached to
step 1, **92 to "Base Corners"** — the tip count tracks where learners actually get stuck.

`lesson_lblsolveai.json` — 213 entries — is the live coach. Each row is a recognised situation and
the sentence to say about it:

```json
{ "content": "White edge in the bottom layer",
  "contenExt": "1) Yellow face up, green facing you. 2) White edge in bottom layer, below red",
  "contenMove": "1) Green faces you. 2) Turn the red face twice (180°) to bring the edge to the top",
  "upFront": [3, 2], "targetColor": [0], "targetStart": [5], "targetEnd": 32,
  "moveUpFront": "L2", "move": "R2", "moveDesc": "Left hand clockwise twice",
  "type_dev": "WF_TIP_F1_SIDE" }
```

Note `move` vs `moveUpFront`: the same physical turn is named differently depending on how the
learner is holding the cube. Hints are expressed **relative to the hands, not to the model**.

The course ladder is explicitly speed-tiered:

| Course | Content |
|---|---|
| LBL | 8 steps: White Petals → White Cross → Base Corners → Middle Edges → Top Cross → Top Yellow → Top Corners → Top Edges |
| Advanced 60s | finger tricks, fundamentals review |
| Advanced 45s | OLL ×7 groups, PLL ×4 groups |
| Advanced 30s | lookahead, speed tips, PLL-5 … PLL-13 |

And `timer_formuladata.json` is a 691-entry algorithm library: LBL 18, CFOP F2L 41 / OLL 43 /
PLL 21, COLL 36, CMLL 40, **ZBLL 472**. Grouped by recognition case
(`OLL-点` dot, `OLL-十字` cross, `F2L-藏角` hidden corner, `F2L-藏棱` hidden edge,
`F2L-拆分` split), each with its own `ignore` facelet mask for recognition. `timer2_phasetraining.json`
turns each phase into a drill with a scramble generator code (`easyc`) and a goal mask.

### 4.3 Everything else in these apps

GoCube's non-Learn keys reveal a heavily gamified shell: ranked 1-v-1 matches with named lobbies
(London/Paris/Rome/New York/Rio), a *scrambling* contest (race to follow a move sequence), TPS
(turns per second) as the unlocking currency — Beginners → Medium → Hard → Expert → Super Expert
gated on `Gain_TPS_of_4_to_open` — XP, levels, wagers, leaderboards by day/week/month/year, plus
`CubeHero` (a rhythm game: `Levels`/`Model` TextAssets carry note lists and beat maps) and
`PaintIt` (`Images` TextAsset: 3×3 colour-pattern puzzles with per-level time limits).

CubeStation adds alliances, avatar frames, a cash shop, emoji, seasonal cube skins
(`cube2512_christmas`, `cube25sales01`, …), robot opponents, and an entire competition hall.

Both bury the learning under an account wall, a store and a battle pass.

## 5. What `kubik/` takes, and what it refuses

**Takes**

1. **Facelet-mask lesson model** (CubeStation). One 54-entry `-1`/`0..5` array expresses entry
   conditions, goal states, quiz diagrams and algorithm recognition. Everything is data.
2. **Orientation gates** (both). A step does not start until the cube is held correctly, and hints
   are phrased relative to the hands.
3. **Quiz-before-algorithm with specific corrections** (GoCube). Predict, then verify, and when
   wrong, be told *which* reasoning failed.
4. **Daisy-first white cross** (both). It is measurably easier than cross-on-the-bottom for a
   first solve.
5. **Named algorithms, not sequences.** "The right-hand algorithm" is taught once and reused in
   four steps.
6. **Human solver as primary, optimal solver as an escape hatch** (CubeStation's split), with
   cancellation and rotation-merging applied to output before display.
7. **Wrong-move audio.** Immediate, non-verbal, eyes-on-cube feedback.
8. **Tip density as a stuck-ness signal.** 92 tips on the hardest step, 2 on the easiest.
9. **Multi-family BLE in one binary** (GoCube does GoCube + Giiker; CubeStation does three GAN
   generations). Combine both sets.

**Refuses**

1. **No account, ever.** Everything works offline; nothing requires a login.
2. **No hardware requirement.** A virtual cube driver is a first-class device, so the entire
   course is usable with a keyboard and a cardboard cube.
3. **No shop, battle pass, XP, wagers or lobbies.** Timer, stats and the course.
4. **No secrets in the tree.** CubeStation ships `FrameworkConfig.ini` in plaintext, containing
   backend hostnames, an app id/secret pair and a base64 log-signing key. Values are deliberately
   not reproduced here; noted only as an anti-pattern, and none of it is used.
5. **No 200 MB download.** Kociemba's 8 MB of pruning tables are generated on first run, not
   shipped.
