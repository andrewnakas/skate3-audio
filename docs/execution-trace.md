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

## Re-derived 2026-09-11, and preserved this time

One boot-armed session (`TRACE_ARM=boot`, `TRACE_MODE=first`, dump 120 s after gameplay, pad
macro of pushes plus a trick and the replay editor) executed **758 of 1,693 (44.8%)**. The set
is tracked at **`docs/audio-executed-set.txt`** with its provenance, because the first
measurement was lost to `.gitignore`'s `out/` rule — a rule that exists for retail-derived game
data, not for measurements a session cannot reproduce without the game.

**758 does not correct the 789 below.** This session has no map switch, and the earlier union's
extra functions were audio-thread streaming paths that a map switch exercises. It is a narrower
session, not a better measurement.

The useful result is the thread attribution, which was never available before:

| thread of first call | functions | scalar | vector |
|---|---|---|---|
| Main XThread | 325 | 324 | 1 |
| **`RwAudioCore Dac`** | **216** | **200** | 16 |
| load_thread | 107 | 105 | 2 |
| render_thread | 68 | 61 | 7 |
| MoviePlayer2 | 15 | 15 | 0 |
| everything else | 27 | 21 | 6 |

This is what the corpus being call-graph bounded from audio seeds actually costs: 325 of the
functions that ran are main-thread and 68 are render-thread. **The audio surface is 216, not
758, and the scalar part of it is 200** — an eight-fold reduction on the corpus's 1,644 scalar
entries, and the only pool Phase 2 should ever have been screening against.

Two things the trace confirms independently of the shadow harness:

- The movie dependency is real and symmetric. `sub_82B28A00` (producer) ran on `MoviePlayer2`
  and `sub_82B28C18` (`EVENT_STOP`) on `RwAudioCore Dac`, while `sub_82B28CC0`
  (`EVENT_SUBMIT`) and `sub_82B28B78` (`EVENT_PLAY`) were **not seen** — `run_trace.sh` does
  not set `skate3_demo_path_play_movies`. That matches the shadow sessions exactly: the
  producer and `EVENT_STOP` arrive without movies, the two consumers need them.
- Phase 3's ordering needs refreshing, and the heavy kernels are unexercised. Only **1,962 of
  9,356** vector instructions ran. `sub_82F56C88` (4,502, not audio DSP), `sub_82B3A048` (645),
  `sub_82B02C30` and `sub_82B09288` (476 each) were all unseen. The heaviest that ran is
  `sub_82B22898` (583), then `sub_82B50380` (217), `sub_82B42C98` (99), `sub_82B399D0` (98).
  Of the 30 vector functions executed, **16** are first-called on the audio thread: that is
  Phase 3's real ordering input.

## Corpus sizing, from `corpus.json`

The corpus file carries two fields per function, `tu` and `vec`, which is enough to size both
remaining phases statically — and not enough to prioritise either.

| | count | note |
|---|---|---|
| scalar (`vec == 0`) | **1,644** | Phase 2's selectable surface |
| vector (`vec > 0`) | **49** | Phase 3's surface |

The 49 vector functions hold 9,356 vector instructions, but `sub_82F56C88` alone holds **4,502
of them — 48.1%**, which is the "nearly half" noted below; it is in the shared-runtime band,
first reached on the render thread, and is not audio DSP. Excluding it, **Phase 3 is 48
functions and about 4,854 vector instructions**, topped by `sub_82B3A048` (645),
`sub_82B22898` (583, the only one of the four heaviest that ran), `sub_82B02C30` and
`sub_82B09288` (476 each).

## Phase 3's gate-1 screen: the vector family is clean

Screened 2026-09-11 from `docs/audio-executed-set.txt`, which is what having that artifact
tracked buys. **16 vector functions executed on the audio thread**, 1,487 vector instructions
between them, heaviest first: `sub_82B22898` (583), `sub_82B50380` (217), `sub_82B42C98` (99),
`sub_82B399D0` (98), `sub_82B44D18` (84), `sub_82B3C098` (69), `sub_82B3D0A8` (56),
`sub_824531C8` (43), `sub_82B389A0` (42), `sub_82B427D8` (36), `sub_82B44B20` (33),
`sub_82B4FD40` (32), `sub_82B373C8` (29), `sub_82B3CF58` (25), `sub_82B3BED8` (25),
`sub_82B238A8` (16).

**Gate 1 closes on the whole subtree: 24 functions screened, zero indirect calls.** Eleven of
the sixteen are outright leaves; the rest bottom out in leaves (`sub_82F52FB8`, `sub_82473930`,
`sub_82F52B30` = `memcpy`, `sub_82B41FC8`, `sub_82B43978`, `sub_82EE7460`, `sub_82F4DFB0`,
`sub_82F4DED0`). That is a structural difference from Phase 2, where gate 1 killed three
candidates outright — worth knowing before estimating Phase 3, because the bottleneck there
will not be finding checkable functions.

Only `sub_82B22898` is entangled: 2,339 lines and five callees, with a subtree that took four
further levels to close. Porting it first would be the wrong order while eleven leaves wait.

### Frequency, measured — and it inverts the order instruction counts suggested

Counting hooks on all fifteen (`skate3_audio_kernel_census`, cvar-gated) over ~100 s:
**15,085,386 calls, every kernel called.**

| kernel | calls | vec | stores | observable result regs |
|---|---|---|---|---|
| `sub_824531C8` | **7,962,020** | 43 | **0** | none |
| `sub_82B44B20` | 3,307,685 | 33 | 9 | none |
| `sub_82B3BED8` | 1,511,888 | 25 | 11 | none |
| `sub_82B3C098` | 1,360,578 | 69 | 12 | none |
| `sub_82B50380` | 254,917 | 217 | **111** | none (memory is the output) |
| `sub_82B399D0` | 206,226 | 98 | 63 | v25–v28 |
| `sub_82B3CF58` | 205,964 | 25 | 6 | none |
| `sub_82B238A8` | 62,397 | 16 | 29 | none |
| `sub_82B3D0A8` | 59,373 | 56 | 24 | none |
| `sub_82B22898` | 40,160 | **583** | 21 | v125–v127 |
| `sub_82B42C98` | 39,156 | 99 | 52 | v29–v31 |
| `sub_82B389A0` | 34,371 | 42 | 8 | v30 |
| `sub_82B44D18` | 25,439 | 84 | 12 | v24–v31 |
| `sub_82B373C8` | 15,208 | 29 | 14 | none |
| `sub_82B427D8` | **4** | 36 | 34 | none |

Instruction count measures **porting effort**, not value, and it was being read as both.
`sub_82B22898` is heaviest at 583 instructions and runs 200x less often than `sub_824531C8`
across 2,339 lines and five callees. `sub_82B427D8` manages four calls — `REQUEUE` again, and
the reason this census exists at all.

### Gate 4: the result has to land where the harness can see it

`sub_824531C8` looked ideal — 113 lines, leaf, 43 vector instructions, eight million calls, and
**zero stores**, so gate 2 is trivially satisfied. It is in fact unportable under this harness,
and nearly became the first Phase 3 port on the strength of that zero.

With no stores there are no memory windows, so its output can only be in the vector registers it
writes: `v0`, `v1`, `v12`, `v13`, `v59`, `v60`. `SHADOW_PRESERVED_VRS` covers `v14`–`v31` and
`v64`–`v127`; the return flags are `kReturnR3`, `kReturnF1`, `kReturnV2`. **None of those six is
observable.** A shadow comparison would compare nothing at all and report a clean pass on every
one of eight million calls — the vacuous green the first negative control exposed, total rather
than partial.

So: **a candidate must produce output the harness can observe** — memory inside a window, or a
register in the preserved set or a `kReturn*` flag. This is a property of the harness, not of the
function, and it is fixable: extend `ShadowReturn` so a hook can name the volatile vector
registers its function returns in.

Note what this does **not** disqualify. "Volatile" is not "not a result" — `r3`, `f1` and `v2`
are all volatile and all return registers. Kernels with substantial stores (`sub_82B50380` 111,
`sub_82B399D0` 63, `sub_82B42C98` 52, `sub_82B238A8` 29) write real guest memory, and *that* is
their observable output; their volatile vector writes are very likely scratch a caller cannot
rely on. Only **register-only** kernels fail gate 4, and on this evidence that is
`sub_824531C8` definitively.

### `sub_82B50380`, the first target, and one hazard it carries

217 vector instructions, 1,284 lines, **no callees**. Gate 3 passes outright: no timebase, no
clock, no indirect resolution. Gate 2 passes too, but only once the store pattern is read
properly:

- 111 stores against 28 loads, so the work is overwhelmingly register-to-register SIMDe
  computation with few memory touches.
- 25 stores go through `ctx.r1` — its own stack frame, scratch that dies with the call. Not
  output, so not something a window has to cover.
- The rest are `stvlx128`/`stvrx128` pairs: **unaligned** VMX stores, each lowered as two byte
  loops that together write one 16-byte vector straddling an alignment boundary. Addresses are
  always `base + offset` register pairs (`ea = r11`, `ea = r11 + r7`, `ea = r11 + r6`, …), never
  a pointer advanced by chasing memory. So every written address is computable from entry
  state — the property `BUFPAIR` has and `sub_82B482F8` lacks.
- Four sites use `ea = (r10 + r9) & ~0xF`, the *aligned* form, so one kernel mixes both.

Two consequences to plan for rather than discover. **The window set is wide** — 14 distinct
base/offset registers feed the stores — so its hook assembles many small spans, which is
bookkeeping rather than a gate failure, and the 64 KB budget wants checking against measured
lengths. And **the unaligned store lowering is a porting hazard in its own right**: `stvlx`
writes `16 - (ea & 0xF)` bytes with lanes indexed `15 - i`, `stvrx` writes `ea & 0xF` bytes
indexed `i`, so a translation that stores a whole vector or reverses the lane order is wrong
**only on unaligned inputs**. `docs/vmx128-exactness.md` probed arithmetic lowerings, not these
store forms, so Phase 0b's GO does not cover it. The per-function bit-compare is what would
catch it.

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
