# The port loop: porting the audio-thread set to native C++

The recomp's audio is already exact, so this does not buy correctness. It buys readable,
fixable C++ and a verified reference for the Rust port, over the **216 functions first called
on `RwAudioCore Dac`** (`docs/audio-executed-set.txt`: 200 scalar, 16 VMX128).

**Decided 2026-09-12 by the user, superseding `docs/PLAN.md`'s "do not sweep the 200".** The
earlier decision was correct on the economics it measured — 12 functions hand-screened for 3
verified — and the sweep is affordable only because that cost was attacked directly:

| the old cost | what replaced it |
|---|---|
| gates screened by reading each body | `probe/screen/census.py`, one pass over `generated/`, all four gates statically |
| one function per build and per session | many hooks per build, one session verifies a whole batch |
| register-only results unobservable (gate 4) | `ShadowResults` mask names any GPR/FPR/VR/CR |
| hook boilerplate hand-written per function | `SKATE3_PORT` generates it; a port supplies `Native` and `Windows` |
| no pass/fail parser | `probe/harness/summarize_session.py`, and a missing runs line is never green |

## The pieces

| file | what it does |
|---|---|
| `probe/screen/census.py` | static census -> `probe/screen/out/census.json`, `docs/ports-static.md` |
| `probe/ports/queue.json` | one record per function: tier, status, gate, call counts, aggregator |
| `probe/ports/queue.py` | `init`, `merge-dynamic`, `tiers`, `next`, `set`, `manifests`, `report` |
| `probe/ports/SUBAGENT_BRIEF.md` | the rules a port author follows |
| `recomp/src/skate3_audio_port.{h,cpp}` | `SKATE3_PORT`, `PortSpec`, `GuestCall`, the census |
| `recomp/src/audio_ports/sub_*.inc` | one file per function: `Native` + `Windows` + one macro line |
| `recomp/src/skate3_audio_ports_*.cpp` | six aggregators; ninja tracks the includes, so one `.inc` edit is one object |
| `recomp/src/skate3_audio_census_all.cpp` | generated counting hooks for every function with no port yet |
| `probe/ports/package.py` | builds the per-function package an author reads |
| `probe/ports/lint.py` | structural check on a `.inc` before a build cycle is spent |
| `probe/ports/promote.py` | applies a session's verdicts to the queue and to each `.inc` header |
| `probe/harness/summarize_session.py` | log -> per-function verdict, exit code |
| `tools/sync_recomp.sh` | `recomp/src` -> `skate3recomp-dev/src`; refuses if the build tree drifted |

One CMake edit added the six aggregators, `skate3_audio_port.cpp` and the census TU, and
delisted `skate3_audio_kernel_census.cpp` (its counters moved into the generated TU). No
further CMake change is needed: a new port is a new `.inc` plus `queue.py manifests`.

## The cycle

```
queue.py next --tier A -n 16      # hottest first
  -> package per function (lifted body + census entry + provenance)
  -> subagents write recomp/src/audio_ports/sub_X.inc + probe/ports/notes/sub_X.md
probe/ports/lint.py                         # before spending a build
queue.py manifests && tools/sync_recomp.sh push && ninja -j10 skate3
nm skate3 | grep ' T sub_X'       # the artifact, never ninja's exit code
run_session.sh LABEL              # SHADOW=true DURATION=110 EXPECT_T=...
summarize_session.py LOG --expect-file ... --json S.json
promote.py S.json --profile boot           # queue + .inc STATUS, in one step
  verified -> status=verified, .inc STATUS and macro flipped to kPortVerified
  diverged -> one more attempt with the divergence line and its vector
  uncalled in boot -> retry in the play/map profile, then stop
```

Max two attempts per function. Verified ports stay armed in later sessions as free regression.

## Harness changes this needed

- **`ShadowResults`** replaces the three-flag `ShadowReturn`: `{gprs, fprs, vrs_lo, vrs_hi, crs}`
  bitmasks with `Gpr(n)`/`Fpr(n)`/`Vr(n)`/`Cr(n)` builders. This is what makes a function with no
  stores checkable instead of vacuously green — gate 4 in `docs/PLAN.md`.
- **Budget overflow is a hard failure.** It used to drop windows past 64 KB and compare the rest,
  which lets a native write land outside them and reach the live game unrewound. Now nothing is
  compared, `stats.overflow` counts it, and the summarizer treats it as a failure.
- **`ShadowNestedReplay()`**, a thread-local set around the native run. A hooked callee reached
  from an outer native replay runs its lifted body and compares nothing; otherwise every count and
  vector doubles.
- **Divergence lines carry both values**, and `skate3_audio_vectors_diverged_only` records only
  the vectors that disagreed — a 200-hook session would otherwise write every call.
- **`skate3_audio_port_census`** counts every hooked function and dumps the first four calls'
  entry registers and thread name, which is what a window builder is derived from.

## Negative controls

A green whose control cannot fail is worthless (`docs/shadow-harness.md` records one that
could not). Three ran before any subagent wrote a port:

| control | result |
|---|---|
| `sub_82B29278`, store offset +364 -> +366 | `diverged`, `run 1 diverges in memory at 40C219DC+0 (lifted 01, native 00)` |
| `sub_82B1D198`, returned sum + 1 | `diverged`, `run 1 diverges in register r3 (lifted B888000000000000, native B988000000000000)` |
| summarizer `--expect` on a name nothing hooks | `uncalled`, not `verified` |

Both perturbations were reverted and the sources restored byte-identical.

## Results so far

**60 functions ported and shadow-verified, zero divergence outstanding.** Every batch is armed
together, so each session re-verifies everything landed before it; the counts below are
comparable calls in one 110 s boot session.

| | |
|---|---|
| verified ports | 60 of 216 |
| comparable calls, best session | ~7.3M |
| divergences found | 2, both mine, both fixed |
| audio real-time rate with all 60 armed | 187.5/s, unchanged |

**Gate 4 is retired as a blocker.** `sub_824531C8` -- four-lane sine, 43 vector instructions,
zero stores, result in v1 -- verified over **6,994,118 comparable calls** in a single session
with the `ShadowResults` mask naming `Vr(1)`. Under the old three-flag `ShadowReturn` that
comparison would have checked nothing at all on seven million calls. Register-only kernels are
now first-class harness targets.

**The plan's open question about shadow overhead is answered: there is none worth managing.**
That session ran the harness on 7.4M kernel calls plus 60 other hooks and `Audio stats` held
187.5/s against a 187.5/s real-time budget throughout, with the minimum sampled rate 174.8/s
during load. `SKATE3_PORT_EX`'s sample shift exists but has not been needed.

### Over-refusal is the other way to be wrong

A window builder that returns false too often produces a green that covers less than it looks
like. Three ports verified clean while skipping most of their calls, and re-reading them showed
two of the three were merely conservative:

| port | before | after |
|---|---|---|
| `sub_82B238A8` | 34% of calls compared | ~90%, 44,883 runs |
| `sub_82B3D4F8` | 66% | ~99%, 128,820 runs |

`sub_82B3D4F8`'s skipped branch was the one that calls `sub_82B3D0A8`, so the harness had never
compared either of the two kernels that dispatcher chooses between. Windowing it also got
`sub_82B3D0A8` its first real verification, at 42,831 calls. In both cases the eighteen store
addresses looked like loop cursors plus deltas built during the call, and the deltas cancel:
every store resolves to one of two arrays named in the descriptor at entry.

The refusals that survived are the instructive half. `sub_82B238A8` still declines a *pending*
ramp, because the generator's fill length is computed in-call from a float conversion that
admits `0x80000000`, which would mean a 2-billion-sample fill; deciding that in the window
builder needs host floating-point inside a hook, which is the documented SIGFPE trap. That is a
length that does not exist before the call -- gate 2 proper, not caution.

**So `skipped` is a first-class result, not a footnote.** The summarizer treats a skip fraction
over 10% as not-green for exactly this reason, and the three ports above were found by reading
that column rather than the divergence count.

### The two divergences, and what they teach

Both were mine, both in functions I hand-wrote, and both would have shipped silently without the
harness.

1. **A misread constant address.** `sub_82B2FE00` loads six pool constants through `lis`/`lfs`
   pairs. I decoded `lfs f13,18868(r9)` as offset 0x4BB4 instead of 0x49B4, so one scale factor
   came from the wrong address: `run 1 diverges in memory at 707BFB20+1 (lifted 34, native A6)`.
   **Rule: compute a constant address as `((imm & 0xFFFF) << 16) + offset`. Never read it by eye.**
2. **A 64-bit sum truncated to 32 bits.** `sub_82B1F360` cascades a six-word counter. RexGlue's
   `add` works on zero-extended 64-bit registers, so a sum carries into bit 32; the stores keep
   only the low word but the RETURN keeps all 64 bits. My 32-bit chain produced byte-identical
   memory and a wrong r3 on the **120th** call: `lifted 94BF290A01000000, native 94BF290A00000000`.
   **Rule: keep 64-bit intermediates through an arithmetic chain and cast only at the stores.**

The second is the more instructive: correct memory hid a wrong register, and the carry appeared
once in 120 calls. No unit test written against the source would have found either.

## Measurements

Static census over the 216 (`docs/ports-static.md`):

| | count |
|---|---|
| gate 1 pass | 142 |
| gate 1 fail | 74 (60 indirect calls, 10 kernel imports, 4 timebase) |
| leaves | 92 |
| no non-stack stores (gate-4 pool) | 38 |
| vector kernels | 16 |

Dynamic census, boot profile, 110 s, all 214 non-legacy functions counted at once
(`probe/harness/out/c1_boot.log`): **212 of 216 called, 50,954,830 calls**, 210 first seen on
`RwAudioCore Dac` and 2 on `MoviePlayer2`. Four never ran. Audio stayed at real time (187.5/s)
with the whole set hooked. Uncalled in boot: `sub_82B305C0`, `sub_82B33870`, and the two legacy
hooks `sub_82B28C18` (`EVENT_STOP`) and `sub_82B4FD40`.

`/proc/self/task/<tid>/comm` does name the guest threads, so thread attribution needs no trace
build — that was an open question in the plan and is now answered.
