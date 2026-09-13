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

## Results: the sweep is complete

**All 216 audio-thread functions have a readable native body. 138 are shadow-verified against
the running original with zero divergence outstanding; the other 78 carry the gate that makes
them uncheckable.** Every port is armed in the same binary, so each session re-verifies all of
them at once: these are not accumulated totals but a figure that survives a rebuild.

| outcome | count | what it means |
|---|---|---|
| verified | 138 | zero register and zero memory divergence against the original, on real game inputs |
| gate 1 | 69 | reaches an indirect call, a lock, an allocation or a release; replaying it on rewound memory is unsound |
| gate 2 | 3 | write set not derivable from entry state |
| gate 3 | 4 | reads `mftb`, so two runs return two values and no comparison can pass |
| uncalled | 1 | passes the gates; no profile reached it |
| pre-existing | 2 | already hooked before this work (`EVENT_STOP`, the XMA probe) |

Final verification, three sessions with all 214 port files armed:

| session | result |
|---|---|
| boot profile, 115 s | 214 expected, 0 not green |
| scripted skate and bail, 150 s | 214 expected, 0 not green; **73.5M counted calls** across all 214 |
| promoted, `--skate3_audio_native=true`, 150 s | **138 functions ran natively**, audio 187.5/s, no crash, capture consistent with the documented layout |

The play profile is what closed the last gap: `sub_82B305C0` never ran during boot and verified
over **100,810 calls** once a scripted session skated and bailed, and `sub_82B33870` was reached
106 times. Both had been recorded as uncalled on boot evidence alone.

**Gate 4 is retired as a blocker.** `sub_824531C8` -- four-lane sine, 43 vector instructions,
zero stores, result in v1 -- verified over **6,994,118 comparable calls** in a single session
with the `ShadowResults` mask naming `Vr(1)`. Under the old three-flag `ShadowReturn` that
comparison would have checked nothing at all on seven million calls. Register-only kernels are
now first-class harness targets.

**The plan's open question about shadow overhead is answered: there is none worth managing.**
That session ran the harness on 7.4M kernel calls plus 60 other hooks and `Audio stats` held
187.5/s against a 187.5/s real-time budget throughout, with the minimum sampled rate 174.8/s
during load. `SKATE3_PORT_EX`'s sample shift exists but has not been needed.

### The build script lied once, and the summarizer caught it

`cycle_build.sh` piped ninja through `grep ... || true` and then read `PIPESTATUS[0]`, which
after `|| true` describes `true`. So one failed build printed its compile error and then reported
success, and the session that followed ran on the **previous** binary. It was caught only because
the summarizer reports a function whose port is not actually linked as `census N` -- the census
hook for that address is still in the old binary -- and never as `verified`. No false verification
reached the queue, but that was the summarizer's design, not the build step's.

Three fixes, each aimed at a different way this could recur:

1. ninja's exit status is now captured directly, not through a pipe.
2. The binary must be newer than every port source in the build tree. `nm` alone cannot tell a
   port hook from a stale census hook: both are strong `T` symbols for the same address.
3. Lint check 8: a port may reference another port's namespace only if that port is in the same
   aggregator TU and has a lower address. The manifest includes in address order, so a forward
   reference fails to compile -- which is how the failure started. Reusing a callee's window
   arithmetic is kept, because it is the one thing that cannot drift.

This is `CLAUDE.md`'s "check the artifact, never the exit status" rule, met from the other side: an
exit status that says *success* is just as untrustworthy as one that says nothing.

### A gate is often a property of one path, not the function

69 functions were labelled gate 1 because they reach an indirect call, a lock, an allocation or a
release. But a *call* that never reaches it is replayable, and the harness has always supported
comparing those and counting the rest: `EVENT_PLAY` predicts its aliasing branch from entry state
and skips it. Applying that to nine gate-labelled ports, measured in one scripted session:

| function | compared | skipped | note |
|---|---|---|---|
| `sub_82B1C210` | 15,804 | 304 | the clamp loop, the substance, runs on the compared side |
| `sub_82B30C50` | 13,240 | 0 | **near-vacuous**, see below |
| `sub_82B33970` | 4,569 | 2,170 | thin: the compared path writes one byte and returns 1 |
| `sub_82B1F440` | 367 | 544 | comparable when the owned instance is already null, and the whole tail compares |
| `sub_828E2E08` | 164 | 0 | the unlink compares; no call was the container's last |
| `sub_828E2F38` | 83 | 2,461 | the stale path writes two real words |
| `sub_828E2EA0` | 42 | 122 | the same function over a different cursor |
| `sub_82B217F0` | 0 | 1 | armed and waiting, like `REQUEUE` |
| `sub_82B218E8` | 0 | 1 | once per boot, and that call took the calling path |

**Zero divergence across all of it**, and seven of the nine went from "cannot be checked" to a real
number. Two report zero comparable calls, which is the `REQUEUE` shape: the predicate is right and
the game did not take that path.

**A zero in the skipped column is not coverage.** `skipped` counts calls where `Windows()` refused,
so it is zero both when the builder brackets everything *and* when the game simply never took the
other path. `sub_82B30C50` is the second kind: all 13,240 calls took the early exit, its 958-line
working path never ran, and what compared was a function that writes nothing and returns 1. It is
recorded as near-vacuous in its own header rather than counted as a win. `sub_828E2E08`'s zero is
the honest kind — the unlink itself compared, on every call that was not the container's last.

**None of the nine is promotable, and the status enum enforces it.** `kPortPartial` is shadowable
but `PortPromoted` tests `== kPortVerified`, so `--skate3_audio_native=true` leaves these on the
original. The reason is specific: each body *does* implement the path `Windows()` declines, so
promoting one would run code that was never compared against anything.

Two safety points, because they are what makes this sound rather than optimistic. An empty-window
split is only safe because `Windows()` and `Native()` read the same guard through the same constant;
if they could disagree, the working path's stores would land outside the windows and reach the live
game. And where the body reads a predicate word *after* one of its own stores, the builder declines
the call rather than assuming no aliasing — which costs a comparison, never correctness.

One split was declined on value rather than safety. `sub_82B28970`'s quiet path writes nothing and
returns a word both bodies load identically: a vacuous green in the gate-4 sense, on a function
that runs once per boot at shutdown, which is exactly when the decoder it tears down exists.

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

### The read set is for replay, and declaring it is nearly free

A port's `Windows()` has two jobs and only one of them affects safety. The **write** spans are what
the harness rewinds, and a store outside them reaches the live game, so they have to be right. The
**read** spans are recorded into a vector and nothing else: they are never rewound, and
`PortSpec::total()` counts writes only, so a read span costs nothing against the 32 KB budget.

That asymmetry is easy to under-use. Five verified ports declared the structures they read and not
the *data* they worked on, and it cost nothing until the Rust translations needed replaying against
real inputs. Then it cost everything: two ring functions reported 312 of 312 and 206 of 206 vectors
**unreplayable**, every one at the ring's data, and three spatial functions could not replay at all
because five rodata cells reached through their callees were never named. A recording that holds a
function's registers and its structures but not its inputs cannot be replayed, and the failure
looks like a broken port rather than a thin recording.

So the rule is: **declare every span the body reads, including what a callee reaches**, and where a
constant belongs to another port, copy its address locally with a comment saying to keep the two in
step — a cross-port reference is what lint check 8 forbids.

Adding those spans to five verified ports changed nothing about their verification, which is the
point and was checked rather than assumed: one scripted session afterwards, **147 ports comparing,
zero divergence**, audio at 187.5 frames a second with no silent submits, and the five carrying
between 74,832 and 312,332 comparable calls each.

One rough edge worth knowing: an overflowing **write** set sets `overflowed` and forces the hook to
skip, while an overflowing read set is silently truncated at 32 spans. A port that needs more read
spans than that will record an incomplete read set and say nothing about it.

### Two ports beyond the 216, because a Rust port needed them

The sweep's scope was the 216 functions **first** called on the audio thread. The image's sine and
cosine fell outside it only because of that attribution: sine is first called on the load thread
and cosine on the main thread. Both also run on the audio thread, through the spatial panner and
the per-channel filter stages, and with no verified body four Rust translations could not be
replayed at all. So both were ported and shadow-verified the same way as the rest:

| function | scripted play | boot | divergence |
|---|---|---|---|
| sine, `sub_82F4DED0` | 436,266 | 414,229 | 0 |
| cosine, `sub_82F4DFB0` | 268,332 | 228,467 | 0 |

Each is a scalar leaf over one shared table: 1/pi, pi in two parts (Cody-Waite), a 2.2e8 range
limit, a NaN, and the odd Taylor coefficients to x^19. Every constant was read out of the image
dump and is read live.

The lesson generalises. Attribution by first call under-counts shared leaves: a routine the whole
game uses gets credited to whichever thread happened to reach it first, so a function outside the
216 can still sit on the audio path. When a port's callee has no verified body, check the callee's
thread by who calls it, not by who called it first.

### A control that never applied looks exactly like a weak test

The commit that fixed the crossfade's gain guard (`3a56902`) says a negative control narrowing the
gain now fails that test. When the message was written, the control had not run. The script that
inserted the mutation asserted that its anchor text appeared exactly once; it appeared twice,
because the public function and its private body end their signatures with the same two lines. The
assertion aborted the script, the file was never changed, and the chain went on to run the
"control" against the unmodified port -- which passed, as an unmodified port should. The pass was
printed, and read past.

Run properly afterwards, both controls fail as they must: narrowing the gain on every path, and
narrowing it in one scalar lane only.

**A control's verdict means nothing until the mutation is confirmed present.** Check that the file
actually changed, or make the mutation step fail the whole chain, before reading what the test said.
A control that silently did not apply reports the same "passed" as a test too weak to notice.

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
