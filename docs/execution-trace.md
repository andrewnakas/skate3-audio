# Guest execution trace: what audio code actually runs

**Phase 0a, measured 2026-09-11. 789 of 1,693 audio-corpus functions (46.6%) executed**
across two automated sessions. Read the two bounds below before using that number.

The first session covered boot, free play and a map switch: 784 functions. A second,
scripted session covered what a player does — skating, a bail and the replay editor — and
added **5**. See "The played session" below.

Reproduce with the tooling in `probe/trace/` — the hook, the rebuild and the run are
described in `docs/environment-linux.md`, "Running the guest trace".

## What the session covered, and what it did not

- **Boot** through the demo path: language select, press start, intro movie completed by
  override. Gameplay reached 13 s after launch.
- **Free play**, signed out, default skater, in University (`DIST_University` in the traced
  string arguments).
- **Pause menu and a map-switch macro** (`map_switch_pcu_library` from
  `freeskate/macros.toml`). All 14 inputs were delivered and the pause was confirmed.
  Whether the second world *finished loading* cannot be read from a `first`-mode trace: the
  loader functions were already recorded for the first world, so a second load adds no
  entries.
- **Window:** from boot to 120 s after gameplay was reached, the tracer's cap.
- **Audio evidence** in the captured string arguments: music (`data\audio/music/world.mpf`,
  `World_Stre…`), a sound bank (`C00_heavy01.abk`), trick audio (`Sk8_Air_Flip_Tri…`),
  announcer speech, `emitter_utility`, and `rw::audio::core::System`.

**Not covered: skating, bails, replay.** The macro presses buttons; it cannot hold a stick.
PLAN's exit criterion asks for "a skate run, and a crash/replay", so this session only
partly meets it.

## The number is two bounds at once

- **A floor on breadth.** A session that also skates, bails and replays can only reach more
  functions, never fewer. 784 is the lowest a representative session will show.
- **A ceiling on audio work.** The corpus is not pure audio. The window holds non-audio
  code — seven vector functions in `0x82B7C000–0x82B84000` were first called on
  `render_thread`, consistent with `decompilation-status.md`'s note that non-audio
  functions fall inside the window — and the closure round adds shared runtime such as
  `memset` (`0x82EE5E80`). The trace's thread column records only the **first** caller,
  so it cannot filter this out; it can only hint.

## Breakdown

| part of the corpus | ran | of |
|---|---|---|
| seed: audio window + 3 out-of-band functions | 663 | 1,536 |
| closure-round callees | 121 | 157 |
| **total** | **784** | **1,693** |

First-calling thread: main 325, `RwAudioCore Dac` 243, load 107, render 69,
`MoviePlayer2` 15, job managers 11, `rwfilesys` 6, remaining 8.

Out-of-band seeds: `sub_82671F50` (Gain fn1) and `sub_82D19648` (named-object lookup) ran,
both first on the load thread. `sub_82D0EBB8` (HwFxReturn fn1) did not.

17,324 distinct guest functions ran in the whole binary over the same window, against
47,652 lifted.

## Vector kernels: what Phase 3 should do first

31 of the corpus's 49 vector functions ran, covering 1,987 of its 9,356 vector
instructions. Counts here include plain VMX alongside VMX128, so they run higher than
`decompilation-status.md`'s `*128`-only figures (`sub_82B3A048` is 645 here, 557 there).

**On `RwAudioCore Dac`** — the DSP that actually runs — by vector instruction count:

| function | vec | | function | vec |
|---|---|---|---|---|
| `sub_82B22898` FrequencyShiftSsb | 583 | | `sub_82B389A0` | 42 |
| `sub_82B50380` | 217 | | `sub_82B427D8` | 36 |
| `sub_82B42C98` | 99 | | `sub_82B44B20` | 33 |
| `sub_82B399D0` | 98 | | `sub_82B4FD40` | 32 |
| `sub_82B44D18` | 84 | | `sub_82B373C8` | 29 |
| `sub_82B3C098` | 69 | | `sub_82B3BED8` | 25 |
| `sub_82B3D0A8` | 56 | | `sub_82B3CF58` | 25 |
| `sub_824531C8` (closure) | 43 | | `sub_82B46D08` | 25 |
| | | | `sub_82B238A8` GainFader | 16 |

**Elsewhere:** render thread 7 (all in `0x82B7C000–0x82B84000`), job managers 4
(`sub_82AF9800`, `sub_82AF9568`, `sub_82AF0338`, `sub_82AF99F0`), load thread 2
(`sub_82473930`, `sub_82EE5E80`), main 1 (`sub_82EDF460`).

**Not seen (18):** `sub_82F56C88` (4,502), `sub_82B3A048` (645), `sub_82B02C30` (476),
`sub_82B09288` (476), `sub_82B3EAA8` (251), `sub_82B40DD8` (226), `sub_82B3FFE0` (221),
`sub_82B08AF8` (162), `sub_82B2A610` (84), `sub_82B356F8` (50), `sub_82B423A0` (48),
`sub_82B42510` (48), `sub_82B43340` (47), `sub_82B2AD50` (45), `sub_82B42268` (39),
`sub_82B41FC8` (20), `sub_82B41ED8` (19), `sub_82B7DAE0` (10).

**PLAN's Phase 3 order was "heaviest first": `sub_82B22898`, `sub_82B3A048`,
`sub_82B02C30`, `sub_82B09288`. Only the first ran.** The FMA-heavy pair, which 0b singled
out, did not execute at all in this session.

`sub_82F56C88` is the largest vector function in the corpus by far — nearly half its vector
instructions — but it sits in the shared-runtime band and is reached from `sub_82B37B08`
and `sub_82B7D920`, the latter first called on the render thread. It is not audio DSP and
should not drive any estimate.

## Phase 2 targets

| function | role | first caller |
|---|---|---|
| `sub_82B28A00` | command queue producer | `MoviePlayer2` |
| `sub_82B28B78` | command consumer | **not seen** |
| `sub_82B28C18` | command consumer | `RwAudioCore Dac` |
| `sub_82B28CC0` | command consumer | **not seen** |
| `sub_82B48530` | command queue | `RwAudioCore Dac` |
| `sub_82B48A50` | scheduler tick | `RwAudioCore Dac` |
| `sub_82B482F8` | scheduler | `RwAudioCore Dac` |
| `sub_82B48440` | scheduler | `RwAudioCore Dac` |
| `sub_82B7F828` | buffer-pair init | main |
| `sub_82B7F998` | buffer-pair | main |
| `sub_82B7F8A8` | buffer-pair measure | main |

The queue producer's first caller is the movie player — the intro movie's audio is the
first thing to submit commands. Two of the three consumers that `command-queue.md` says
define the wire format never ran, so shadow-verifying them needs a session that reaches
whatever command types they handle.

## The played session, 2026-09-11

No human was available, so the pad was driven from a script instead
(`docs/input-harness.md`): pushes, an ollie, five bail attempts and the replay editor, 66 s
of timeline in PCU Library. Frames confirm what happened — the skater crossed the plaza and
rode to a different area, one real bail occurred (the game's own `IsWipeoutRequested`), and
the replay editor opened with its timeline and transport controls on screen.

| | ran | new |
|---|---|---|
| session 1: boot, free play, map switch | 784 | — |
| session 2: scripted skating, bail, replay | 760 | 5 |
| session 3: scripted bail attempts, spaced | 789 | 0 |
| **union** | **789 of 1,693 (46.6%)** | |

The third session reached all 789 **on its own**, and no session holds a function the others
lack. Boot into a world plus a few minutes of scripted play is the whole reachable set these
sessions find.

The five the played session added are all in the audio window: `sub_82B301C0`,
`sub_82B301C8` (first called on a worker thread), `sub_82B305C0`, `sub_82B33870` (audio
thread) and `sub_82B715B0` (main). The first session holds 29 the played one does not, every
one first called on the audio thread — the streaming paths a map switch exercises and a
single world does not. Vector coverage did not move: 31 of 49 in both.

**So the exit criterion is met, and breadth saturates early.** A session covering menu, a
skate run and a bail plus replay reaches almost exactly what boot and a map switch already
reached. What is left unreached is not gameplay-shaped: it is content the sessions never
touched (other modes, other worlds) plus code in the corpus that is not audio at all.

Unreached in these sessions, but since measured: `sub_82B28B78` and `sub_82B28CC0` — two of
the three command-queue consumers — ran in neither traced session, because both need frontend
movie playback and these sessions skip it. With `skate3_demo_path_play_movies=true` both run:
`EVENT_SUBMIT` (`sub_82B28CC0`) 1,678 times per boot, and `EVENT_PLAY` (`sub_82B28B78`)
**exactly once** per boot, at the single FMV's start. The **not seen** rows above are a fact
about the trace, not about the functions; see `docs/shadow-harness.md`.

## The 789-function list is not on disk

Only the **count** survives, in this document. `probe/trace/out/corpus.json` is the 1,693
function *corpus* — keyed by address, no per-function seen flag — not the executed set, and
the per-session traced sets were not kept. This document names 63 distinct functions out of
the 789 it reports, so **absence from the tables here is not evidence a function never ran**.

That matters in practice: `sub_82B48B28` is in the corpus, is absent from every table here,
and ran zero times in a shadow session — and those three facts together still do not say
whether the Phase 0a trace reached it. Re-deriving the list costs one traced session
(`probe/trace/trace_hook.py apply`, then a rebuild), so it is reproducible rather than lost,
but it is not retrievable by reading.

## Next

More sessions add little breadth, so further tracing is not the lever. If a specific
function needs to be reached — a command consumer, an unrun kernel — drive the feature that
uses it rather than playing longer.
