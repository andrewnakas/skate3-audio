# Working on this project

You are picking up reverse-engineering of Skate 3's audio. Read this before touching
anything; it encodes several days of work and the specific mistakes that cost the most
time.

**Then read two more files, in this order:**

1. **`docs/environment-linux.md`** — this document was written on an 8 GB macOS M1. If you
   are on the Linux box, several statements below are **false there**, including the build
   trap about hooks forcing a full rebuild. That file says what was actually measured.
2. **`docs/PLAN.md`** — the sequenced plan. Sequencing is settled: **recomp first, verified
   under the shadow harness, then port the proven result to Rust.**

## The goal

Audio that is **exact** in two places:

1. **skate3recomp** — native C++ replacing the recompiled guest audio code, provably
   equivalent.
2. **skate-3-rust-engine** — a Rust implementation, which today has no audio at all.

"Exact" has a measurable definition here, and you must keep it that way: the guest mixer's
own output, tapped by `audio_dump_path` before any downmix, compared bit-for-bit with
`tools/mixdiff.py`. Anything softer is unfalsifiable.

## Reframing you need before planning work

**The recomp's audio is already exact.** It runs the original PPC code, faithfully
translated. It measures clean: 187.5 frames/s dead on real-time, zero errors, audio decode
at **0.4% of one core**. Native replacement there does not buy correctness and does not
buy performance. It buys code you can read and fix, and a verified reference for the Rust
port. Those are the real motives — do not let anyone (including yourself) justify the
effort on correctness grounds.

The Rust engine is the opposite: no audio exists, so implementation is the only path.

## Current state

| area | state |
|---|---|
| Decompilation | complete — 1,694 functions, call-graph bounded, full coverage |
| Symbols | 421 names applied; retail build has **RTTI stripped**, names come from plug-in metadata |
| Structures | 7 structs, 35 asserted offsets (`docs/rw_audio_structs.h`) |
| Container formats | all three decoded and documented |
| Conversion | **sample-exact** on ambience, speech and music -- and reproducible with the `ffmpeg` **binary alone**, no `libavcodec` headers, by padding each chunk to a 2048-byte packet multiple before concatenating (`docs/xma-transcode.md`, the 2026-09-12 correction) |
| Audio in the Rust engine | **plays real streams**: `crates/skate-data/src/audio/` decodes a retail archive member byte-exactly and a Bevy source plays it. Choosing a stream by name still needs the undecoded metadata table |
| Rust crates | **two**. `skate-audio-formats`: 33 tests, three containers, validated on real archives. `skate-audio-core`: started 2026-09-11, the queue path ported from the shadow-verified C++ (`system.rs`, `player.rs`, 11 tests) — **tier 1 met**: every comparison of a complete session — **8,607** real recorded vectors — replayed against the C++'s own results, 0 disagreements, four functions (`system.rs`, `player.rs`, `buffers.rs`), 13 unit tests, four negative controls that fail correctly. Read the limits in `docs/shadow-harness.md` before quoting the number |
| Shadow harness | **proven** and extended: `ShadowResults` compares any GPR/FPR/VR/CR, budget overflow is a hard failure, nested replays are suppressed (`docs/shadow-harness.md`) |
| Native functions | **the sweep is COMPLETE, 2026-09-12: all 216 audio-thread functions have a body; 138 shadow-verified with zero divergence.** The other 78 carry the gate that makes them uncheckable: 69 gate 1, 3 gate 2, 4 gate 3, 2 pre-existing. Do not re-port any of them — read `docs/ports.md` for per-function status and `docs/port-loop.md` for how the loop runs |
| Guest-mix capture | `audio_dump_path` written for Linux and validated; **not reproducible run to run** |

### What to work on next

The native sweep is finished, so the live fronts are:

1. **Promotion.** The 138 verified bodies run only behind `--skate3_audio_native=true`. Which
   should become the default is a judgement separate from proving them equal, and it is open.
2. **The Rust engine** (`docs/PLAN.md` Phase 4). Every function it needs now has a verified or
   gate-labelled C++ reference in `recomp/src/audio_ports/`, so each port is transcription, not
   analysis. `scheduler.rs`, `xma.rs`, `dsp/` and `graph.rs` are unwritten.
3. **`.mpf` sequencing sections 0–3** — the headline format gap, below.
4. **Bug 1's ordering fix**, now that `docs/command-queue.md` records a *second* producer.

### Open

- **`.mpf` sequencing semantics.** Top-level structure decoded (72-byte header, 9 sections,
  section 7 links to the `.mus` by content hash, section 8 is 8 bytes per segment). How
  sections 0–3 drive transitions is untouched. Interactive music needs segments *plus* a
  usable map. The `.mus` side is now complete: its header is decoded and all 8,179
  segments walk against the SNR table (`docs/rust-port.md`). Note the `.mus` field at
  `0x28` is **not** the hash `.mpf` links by — that was checked and found absent.
- **The low-bit flag** in the chunk length field. Constant per stream, meaning unknown.
- **Recomp bugs.** **Bug 3** (negative buffer size) has a **guard landed on Linux**:
  `skate3_audio_buffer_size_guard`, default on, clamps a negative length to zero at the point of
  damage in `sub_82B7F828` — verified free over 226 comparable calls with zero firings. It is
  deliberately the weaker of the two fixes: the upstream validation belongs in `sub_82B7F8A8`,
  which the harness **cannot bracket** (its window length is computed by a callee mid-call), and
  post-hoc detection is impossible because the descriptors die with that callee's stack frame.
  Note the mitigation `docs/buffer-size-bug.md` describes in the present tense does **not exist
  on the Linux tree** — `skate3_audio_fixes.cpp` is absent there, so this guard is the only
  protection. **Bug 1** (the command-queue ordering race) is **not landed**:
  `docs/command-queue.md` specifies what a fix must achieve, not an implementation, and landing
  it diverges from the original by construction, which the harness cannot distinguish from a
  porting mistake. See `docs/command-queue.md` and `docs/buffer-size-bug.md`.
- **Bug 2** (`0x8210A310` corruption): source string identified, but pinning the writer
  needs QCS8550 hardware.
- ~~**VMX128 exactness is unquantified.**~~ **Measured, 2026-09-11: GO.** It was the
  single biggest risk in any effort estimate; it is now retired as a blocker.
  45 of 45 operations, spanning every distinct lowering family in the 76-mnemonic audio
  surface, are bit-identical between RexGlue's C++ and a Rust translation — 56,880 lane
  comparisons, both flush-to-zero states. Run `probe/vmx128/run.sh` to reproduce; it needs
  no Ghidra, no game build and no play session. Full cookbook in
  `docs/vmx128-exactness.md`. What survives, both narrow: `vexptefp128`/`vlogefp128` go
  through libm and match only because Rust and glibc share a symbol here, so keep them
  bit-checked forever; and commutative float ops are **not** NaN-commutative, where the
  winning operand is chosen by register allocation in GCC and in clang-20, the recomp's own
  compiler, so it cannot be derived from source (cookbook rule 4).
  Whole-kernel composition is still unproven — that is Phase 3.

### The measurement to take first (still worth doing, but it no longer gates anything)

Nobody knows how many of the 1,694 functions actually *execute* during play. The recomp
has a guest tracer (`src/skate3_guest_trace.cpp`, compiled out by default). Build with
`-DSKATE3_GUEST_TRACE=ON`, run with `--skate3_trace=true --skate3_trace_mode=first`, then
intersect the traced set with the audio corpus. That turns the effort estimate from a guess
into a number. Do this before committing to a plan.

Note it traces breadth, not frequency, and filters by address range rather than thread — so
treat the result as an **upper bound**.

On the Linux box the tracer's cvars are compiled in but **its recording hook is not** —
the docs said otherwise until 2026-09-11, and an armed trace would have dumped nothing.
Apply it with `probe/trace/trace_hook.py apply` and rebuild (195 s, measured). Run it. But it no longer gates the plan: that framing
assumed no audio instrumentation existed anywhere, and the work it informs (which functions
to port first) comes after the harness is up. See `docs/PLAN.md` phase 0a.

**Measured 2026-09-11: 789 of 1,693 corpus functions ran** across three automated sessions —
boot with a map switch, and scripted sessions that skated, bailed and opened the replay
editor (`docs/input-harness.md`). The scripted ones added 5 over the first, and the last
reached all 789 alone, so breadth saturates;
the number is still a ceiling on audio work. Of the four heaviest VMX128 kernels only
`sub_82B22898` ran. `docs/execution-trace.md` has the lists.

**Re-derived and tracked 2026-09-11: `docs/audio-executed-set.txt`.** One session reached 758
(narrower — no map switch), and the attribution is the part that matters: **216 of those are
first-called on `RwAudioCore Dac`, 200 of them scalar.** The other 542 are main-thread (325),
load_thread (107), render_thread (68) and so on — the corpus is call-graph bounded from audio
seeds, so most of what "ran" is not audio. Screen Phase 2 candidates against the 200, not the
corpus. Of 30 vector functions executed, 16 are audio-thread: that is Phase 3's ordering input,
and the four heaviest kernels did not run at all.

## Workflow for native audio

The sweep is done, so this is now the recipe for *revisiting* a port — tightening a window,
fixing a divergence, or promoting one — not for starting from nothing. It is automated; use the
tooling rather than the steps it replaced.

```sh
SK8_PKG_DIR=/tmp/pkg python3 probe/ports/package.py ADDR   # body + census + store provenance
$EDITOR recomp/src/audio_ports/sub_ADDR.inc                # Native() and Windows() only
python3 probe/ports/lint.py                                # 8 structural checks, pre-build
probe/ports/cycle_build.sh /tmp/expect.txt                 # manifests, sync, build, artifact check
OUT=$PWD/probe/harness/out SHADOW=true PORT_CENSUS=true DURATION=110   EXPECT_T=/tmp/expect.txt probe/harness/run_session.sh LABEL
python3 probe/harness/summarize_session.py probe/harness/out/LABEL.log   --expect-file /tmp/expect.txt --json /tmp/s.json
python3 probe/ports/promote.py /tmp/s.json --profile boot   # queue + .inc STATUS
```

A port supplies only `Native()` and `Windows()` inside `namespace port_ADDR`, plus one
`SKATE3_PORT(...)` line; the macro generates the census, shadow and promotion wrapper. The
window builder is the only per-function intelligence, and `docs/port-loop.md` explains what it
must cover. Read `probe/ports/SUBAGENT_BRIEF.md` for the exact-semantics rules — store order,
`fctidz` edges, FMA versus separate multiply, flush-mode call points.

Three profiles matter, and one session is not enough: the **boot** profile misses functions that
only a played session reaches. Two functions read as never-called on boot evidence and then
verified over 100,810 and 106 calls under a scripted skate-and-bail
(`INPUT_SCRIPT=probe/trace/scripts/bail_replay_v2.txt`).

The harness runs the original first and keeps its result, then runs yours against a rewound
copy and discards it. A wrong native implementation cannot corrupt the running game **as long as
every byte it writes is inside a declared window** — that is what `Windows()` is for, and a write
outside them is never rewound. So it is safe to leave armed through normal play, and the game
generates far better test inputs than anything you would write, at 187.5 frames a second.

**Adding a port costs one aggregator compile plus a relink**, roughly 4 s: the `.inc` files are
included by six TUs that ninja tracks. No CMake edit, no batching. The macOS full-rebuild trap
below does not apply here.

## Traps that cost real time

**Launching without the title update looks like total audio failure.** `skate3_install_tu`
is documented "empty to ask", so without it the game sits on an installer overlay, the main
guest thread blocks holding a critical section, and audio reports *100% silent submits with
zero XMA voices*. Always pass
`--skate3_install_tu=<TU_12K2276_...>`. This cost an hour.

**Host float work inside a guest call can SIGFPE.** The audio worker thread enters guest
code with MXCSR `0x0000`, every FP exception unmasked. The first capture tap divided a
double on close and killed the game at the 4,000th submit. Mask exceptions around host-only
work in hooks — `FloatExceptionsMasked` in `skate3_audio_dump.cpp`.

**Adding a hook forces a full rebuild.** `generated/skate3_hooked_funcs.h` is included by
`skate3_init.h`, which every translation unit includes. One new hook rebuilds everything.

> **Not true on the Linux tree.** That header and `gen_hooked_funcs.sh` do not exist
> there; hooking is link-time weak-symbol override, so a new hook costs one TU compile
> plus a relink. Batching is unnecessary. Verified with `nm` — see
> `docs/environment-linux.md`.

**Never put defines in `CMAKE_CXX_FLAGS`.** It invalidates every third-party library in the
tree — turns a 200-file rebuild into a 700-file one. Use `target_compile_definitions` on
the `skate3` target.

**`polite_build.sh` suspends compilation while the game runs.** If a build appears hung,
check for a live `skate3` process. It also throttles on low memory; on a machine with
plenty of RAM you can build directly.

**Run `FixHelpers` before decompiling.** Xenon prologues call `__savegprlr_*` register-save
stubs; Ghidra models them as ordinary functions, so `r3` is lost and replaced by a fake
return value. Without the fix, *most* functions have wrong parameters and any struct-offset
work built on them is silently wrong.

## Methodological warnings, earned the hard way

**Synthetic tests have never once caught a format bug here. Real data has caught every
one.** Four separate occasions. Unit tests prove the code is self-consistent, which is
exactly what a wrong format assumption preserves. The `rust/*/examples/verify_*.rs`
programs run the same code over real archives — those are what find things. Run them
against **all three** classes before claiming a format works.

**Do not generalise from the head of a distribution.** This produced three confident wrong
answers: the chunk length field read as a bit offset, then as two per-container biases, and
a `.mpf` field read as a duration because its first six records happened to match. Each was
consistent with the evidence gathered at the time. Check the whole distribution.

**A coherent story that explains several loose ends at once is the most dangerous kind.**
It feels like insight. Verify it anyway.

**Compute a `lis`-based constant address, never read it by eye.** `((imm & 0xFFFF) << 16) + offset`.
Misreading one digit of `lfs f13,18868(r9)` produced this project's first shadow divergence, and a
second wrong value reached a committed note before another pass caught it. The arithmetic is three
characters of Python; the guess costs a session.

**RexGlue's `add` and `mullw` are 64-bit on zero-extended operands.** A sum can carry into bit 32.
Stores keep only the low word, so a chain truncated to 32 bits leaves memory **byte-identical** and
the returned register wrong — which surfaced on the 120th call of one function. Keep 64-bit
intermediates and cast at the stores.

**A window builder that refuses too often is also wrong.** It produces a green covering less than
it looks like, so `skipped` is a first-class result, not a footnote. Two ports verified clean while
declining two thirds of their calls; re-reading them lifted one to ~90% and the other to ~99%, and
the second earned a kernel its first real verification because the skipped branch was the only
path that called it.

**An exit status saying *success* is as untrustworthy as one saying nothing.** `cycle_build.sh` read
`PIPESTATUS` after `|| true`, so a failed build printed its error and reported success, and the next
session silently ran the previous binary. Check the artifact: the object file, the `nm` symbol, and
that the binary is *newer* than its sources.

**Grep on decompiled offsets does not discriminate.** Offsets like `+0x30`, `+0x34`,
`+0xCC` appear on unrelated structures; searching for them returns noise. Three separate
hunts failed this way. Read the specific function, or instrument the running game — the
runtime probe answered in one capture what static search had missed for hours.
