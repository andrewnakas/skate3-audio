# Plan: exact audio in the recomp, then in Rust

Sequencing decision, settled by the user: **recomp first, verified under the shadow
harness, then port the proven result to Rust.**

The reasoning: the shadow harness verifies a native function bit-for-bit against the
*running original* at 187.5 frames a second, on game-generated inputs far better than
anything hand-written, with no risk to the running game. The Rust path has no equivalent
oracle. So every function that reaches Rust is a port of something already proven exact,
and when Rust diverges the C++ reference is known-good and the delta is the port itself.

## What this plan is grounded in

Written against the repo docs plus measurements taken on this machine rather than
inherited from them. The measurements that changed the plan are in
`docs/environment-linux.md`; read that first if you are picking this up cold, because
several things `CLAUDE.md` states are true of the macOS tree and **not** of this one.

## 1. The shared spine, and where the two tracks diverge

Both targets are first-class. They share less than it looks:

**Shared, done once:**
- Reading each guest function (Ghidra C where it exists, RexGlue lifted C++ otherwise).
- Struct-layout recovery (`docs/rw_audio_structs.h`) — one source of truth that both a
  C++ struct and a Rust struct are written against.
- For VMX128 kernels, establishing lane layout and arithmetic by reading the lifted form.

**Diverges immediately after:**
- **Recomp**: write native C++, shadow-verify against the live game, land it. Deliverable
  is readable, fixable, still-equivalent C++ plus the two unlanded bug fixes.
- **Rust**: mechanically translate the *verified* C++ — not the raw decompiled form. That
  makes it a transcription risk, not a semantic-understanding risk.
- **Containers** (`rust/skate-audio-formats`) are **Rust-only**. The recomp never parses
  `.sns`/`.dat`/`.mus`; it runs the guest's own parser. Not shared spine — an independent
  track that can run the whole time.

Read once, prove once in C++, port and re-check once in Rust.

## 2. Phases

### Phase 0 — free measurements, no rebuild, start immediately

**0a. Guest execution trace.** This section originally said the tracer was already compiled
in and needed no rebuild. **Wrong:** its cvars are, its recording hook is not. Apply the hook
with `probe/trace/trace_hook.py apply` and rebuild — 127 objects, 195 s, measured. Then
`probe/trace/run_trace.sh LABEL [MACRO]`. Details in `docs/environment-linux.md`.

Intersect the traced address set with the audio corpus. The 1,694-function list did not
survive (`out/` is not committed); `probe/trace/corpus.py` rebuilds it from `generated/`. The
documented 1,536-function seed comes back **exactly** as the audio window plus the three
out-of-band audio functions; one closure round gives **1,693**, one short, and resolving
branch targets by address instead of by lowered call recovers nothing more.

*Exit criterion:* a number — "N of 1,694 functions execute during a representative
session covering menu, a skate run, and a crash/replay." It is an **upper bound**:
address-range filtered, not thread-filtered, breadth not frequency. Use it to order Phases 2 and 3 by what is actually reachable.

**Result, 2026-09-11: 789 of 1,693 (46.6%)** across three automated sessions — the last one
reaches all 789 by itself — and the exit criterion is **met**. The first covered boot, free play and a map switch (784). The second
was driven by a scripted pad timeline — skating, a bail confirmed by the game's own
wipeout decision, and the replay editor — and added 5. Breadth saturates: playing more
does not reach more. The number stays a ceiling on audio work, because the corpus holds
code that is not audio. Breakdown and the reordered kernel list in
`docs/execution-trace.md`; the harness is in `docs/input-harness.md`.

**0b. VMX128 pathfinder spike. DONE — result GO.** See `docs/vmx128-exactness.md`;
reproduce with `probe/vmx128/run.sh`.

45 of 45 operations bit-identical across 56,880 lane comparisons, covering every distinct
lowering family in the 76-mnemonic surface, under both MXCSR flush-to-zero states.

The spike was done per *operation* rather than per kernel: each of the five heaviest
kernels calls between three and nine other guest functions, so a standalone link needs
stubs, whereas the go/no-go question is answered more decisively and more cheaply at the
instruction level — and that is also the form the cookbook wanted.

One rule beyond those anticipated: **commutative float ops are not NaN-commutative**, and the
winning operand slot is chosen by register allocation — in GCC and in clang-20, the
recomp's own compiler — so it is not stable across calling contexts. That is the only
divergence found and it is confined to NaN inputs. Rule 4 in the cookbook.

Two corrections to what this section assumed: `sub_82B22898` has **zero** FMA sites (it is
the largest kernel, not an FMA-heavy one — those are `sub_82B02C30`/`sub_82B09288`), and
the build needs **`-std=c++23`**, not C++20.

Neither blocks Phase 1. Run them while Phase 1's build is going.

### Phase 1 — instrumentation in this tree, harness proven (critical path, step one) — DONE

1. Add `recomp/src/skate3_audio_{native,probe,shadow}.cpp` to `SKATE3_COMMON_SOURCES` in
   `skate3recomp-dev/CMakeLists.txt`, the same list `src/skate3_native_scene.cpp` is in.
   Do **not** look for `gen_hooked_funcs.sh` — it does not exist here and is not needed;
   the weak-alias override already does the job.
2. Build once, and **time it** — that number replaces guesswork in every later estimate.
3. Write the `audio_dump_path` tap. **This is new work, not a drop-in** — no source for it
   exists in this tree or its history. Find the pre-downmix mix point (the System tick /
   drain path in `docs/command-queue.md` and `rw_system` is the right neighborhood), hook
   it following the read-only, cvar-gated, capped pattern `skate3_audio_probe.cpp`
   already uses. The output contract is already specified and therefore falsifiable:
   256 frames x 6ch big-endian float32, **planar**, 6144 bytes per submit.
4. Play with `--skate3_audio_shadow=true` and confirm `EVENT_SUBMIT` (written, never
   verified) reports **zero divergence**, then promote with `--skate3_audio_native=true`.
5. Capture once and confirm `tools/mixdiff.py` reads it and reports self-identity.

*Exit criterion:* both of (a) a session log with zero `EVENT_SUBMIT` divergence, and
(b) one capture matching the documented byte layout exactly and readable by `mixdiff.py`.
One proves the shadow mechanism, the other proves the oracle tap.

This is step one because every later verification depends on both halves working.

**Result, 2026-09-11: both halves met.** (a) `EVENT_SUBMIT` ran 1,678 times under shadow
with zero register and memory divergence, then ran natively at least 1,024 times from boot
to gameplay. (b) A 4,000-submit capture passes a signal-level layout check and `mixdiff.py`
reads it. Recomp branch `audio/phase1-harness`, commit `e581969`. What changed on the way,
all detailed in `docs/shadow-harness.md`:

- `ShadowCompare` had to be reworked before it could pass a correct function: a whole-context
  memcmp became ABI-preserved registers, and one window became a list.
- `EVENT_SUBMIT` only runs while a frontend movie plays. The demo path skips movies unless
  `skate3_demo_path_play_movies=true`.
- The tap overrides the `XAudioSubmitRenderDriverFrame` import rather than hooking the System
  tick. Its first version crashed the game: the audio worker enters guest code with MXCSR
  `0x0000`, so host float work there has to mask exceptions.
- **Captures are not reproducible run to run** — 72–78% of aligned submits match between
  sessions. See the caveats on Phases 4 and 6, and risk 7.

### Phase 2 — struct layouts and scalar plug-in logic, native C++

> **COMPLETE, 2026-09-12, and by a route this section argued against.** The "do not sweep the
> 200" decision below was correct about the economics it measured — 12 functions hand-screened
> for 3 verified — and the user reversed it once scripted screening, batched verification and a
> result-register mask changed those economics. **All 216 audio-thread functions now have a
> native body; 138 are shadow-verified with zero divergence.** Results in `docs/port-loop.md`,
> per-function status in `docs/ports.md`. The reasoning below is kept because the gates it
> earned are still the screening rules, and because the cost estimate was right for the method
> it was estimating.

In Phase 0a frequency order where available, else call-graph order:

- Command queue producer/consumer (`sub_82B28A00`, `sub_82B28B78/C18/CC0`, `sub_82B48530`) —
  land the ordering fix from `docs/command-queue.md` natively. In the 0a session
  `sub_82B28B78` and `sub_82B28CC0` never ran; **both have since been reached**, with
  `skate3_demo_path_play_movies=true` — `EVENT_SUBMIT` 1,678 calls per boot, `EVENT_PLAY`
  exactly one, at the FMV's start. A once-per-boot function caps what any single session
  can establish; see `docs/shadow-harness.md`.
- Scheduler tick (`sub_82B48A50`, `sub_82B482F8`, `sub_82B48440`).
- Buffer-pair init/measure (`sub_82B7F828`, `sub_82B7F998`, `sub_82B7F8A8`) — land the
  fix from `docs/buffer-size-bug.md`.
- Scalar plug-in math: filters, panners, submix, gain/dynamics — ~~whatever 0a shows runs~~.
  **This bullet needs re-scoping, not grinding (2026-09-11).** Two measurements broke it.
  `probe/trace/out/corpus.json` carries `tu` and `vec` per function and nothing else, so
  `vec == 0` selects scalar candidates statically — **1,644 of the 1,693** — but there is no
  seen flag, and the 789-function executed set is not on disk (see `docs/execution-trace.md`).
  So candidates can be *selected* without a session and cannot be *prioritised* at all: "what
  0a shows runs" is not available to read.
  Against an unprioritised 1,644, the observed rate does not support a sweep. Screening about a
  dozen candidates produced 3 verified and 1 promoted against 8 disqualified — 3 on gate 1, 3 on
  gate 2, 1 on gate 3, and one that passes every gate and is never called. Each verified
  function cost a read, a build and a session. Extrapolating that is hundreds of hours for a
  deliverable whose stated motive is readable code and a Rust reference, not correctness.
  **Decided 2026-09-11, by measuring first.** The executed set was re-derived in one traced
  session (`docs/audio-executed-set.txt`, tracked) and the pool is far smaller than 1,644:
  filtering by *ran* and by *first called on `RwAudioCore Dac`* gives **216 audio-thread
  functions, 200 of them scalar**. That is the pool Phase 2 should have been screening against
  all along — 325 of the functions that ran are main-thread and 68 render-thread, artefacts of
  the corpus being call-graph bounded from audio seeds.
  **Do not sweep the 200.** At the observed yield — 12 screened for 3 verified and 1 promoted,
  against 8 disqualified, each verified function costing a read, a build and a session — 200 is
  tens of hours, for a deliverable whose stated motive is readable code and a Rust reference,
  not correctness. The recomp's audio is already exact.
  So Phase 2's deliverable is the **verified queue-path reference plus the proven harness**:
  producer (6,706 calls), `EVENT_SUBMIT` (promoted), buffer-pair init (226), `EVENT_PLAY` (one
  input point), and the three gates that say which functions are checkable at all. Phase 4 is
  next on the critical path; return here selectively when Phase 4 needs a specific function,
  screening it against the gates and the 200.

Per function, screen against **three** gates before writing anything — each one cost a
wasted candidate to learn:

1. **Callees replayable.** A function that releases, frees, signals or submits cannot be
   replayed against rewound memory, and is verifiable only on paths that avoid those calls.
   Screen *transitively*: `sub_82B48440` looks clean until `sub_82B49280`, two levels down,
   turns out to make two indirect calls.
2. **Written-address set statically enumerable, and within the 64 KB window budget.** The
   harness only rewinds what its windows cover, so a write outside them lands in the live
   game. `sub_82B482F8` passes gate 1 and fails here: it walks a list of unknown length and
   performs doubly-linked surgery across three objects per node, so the addresses are
   data-dependent and cannot be enumerated before the call. `sub_82B7F8A8` fails it a second
   way: its `memset` length is `r29 + r27`, both read out of stack scratch that a callee fills
   *during* the call, so the window cannot be sized until the work has already happened. `sub_82B7F828` looked like it would fail here too, by
   `memset`ting two caller-supplied buffers of caller-supplied length — **measured, it
   passes**: 192 and 196 bytes on the first call, maxima 400 and 256 across a session, against
   a 65,536-byte budget. The inference would have disqualified a portable function, so it was
   downgraded to a suspicion and then measured. A native port still needs a self-guard, since
   those maxima describe the calls observed and not the function's range.
3. **Output deterministic.** `sub_82B1F7E8` is seven lines, a leaf, and hot — and it is
   `mftb`. Two runs return two different values, so the registers always diverge; and since
   it writes no memory, comparing nothing instead would make the result vacuously green.
   Neither failure is informative, so it is not a harness target at all.

Then read it, write native C++, shadow-verify to zero divergence, promote. Gate 1 comes
first because it is cheapest to check — `EVENT_STOP` turned out to have no such paths in
practice (0 comparable calls in a session). See `docs/shadow-harness.md`. Because
a hook is now a TU compile plus a relink rather than a full rebuild, run this as a **tight
one-function-at-a-time loop**, not batched per build cycle.

*Exit criterion, per function:* zero divergence over a session exercising its path, **with
the comparable-call count recorded next to it**. Zero divergence over one call and over
10,000 read identically and mean very different things, and some of these functions fire
once per boot — so the count, and the inputs it covered, are part of the result.
*Phase:* ~~every function 0a calls hot is native and promoted~~ — replaced 2026-09-11. The old
criterion referred to the 0a executed set, which at the time survived only as a count; it is now
tracked (`docs/audio-executed-set.txt`), and the criterion it implied — port all 200 audio-thread
scalar functions — is explicitly **not** the goal, per the bullet above. The phase is met when
the queue path has a verified native reference Phase 4 can translate (it does), the harness is
proven (it is), and the gates are written down so the next candidate is screened rather than
guessed at (they are). Both known bugs landed
is still a real criterion: bug 3 has a guard at the point of damage (`docs/buffer-size-bug.md`),
and bug 1's ordering fix is specified only as an objective, not an implementation
(`docs/command-queue.md`).

### Phase 3 — VMX128 kernels, native C++

> **COMPLETE, 2026-09-12.** 14 of the 16 audio-thread vector kernels are verified; two carry
> gate 2. The two open items named below are both resolved: `ShadowCompare` did **not** need a
> buffer-output variant (the window list plus a `ShadowResults` register mask sufficed), and
> **gate 4 is retired** — `sub_824531C8`, the zero-store sine kernel, verified over **6,994,118
> calls** once arbitrary result registers could be named. Shadow overhead on that kernel proved
> negligible, so the sampling fallback was never needed. `sub_82B50380`'s gate-2 verdict stands,
> re-derived independently while porting it.

**Screened 2026-09-11 (`docs/execution-trace.md`).** The audio-thread surface is **16 kernels,
1,487 vector instructions**, and **gate 1 closes across all 24 functions in the subtree with
zero indirect calls** — unlike Phase 2, where gate 1 killed three candidates. Eleven are leaves.
Frequency is measured, not assumed (`skate3_audio_kernel_census`): 15,085,386 calls across
~100 s, and the order is not the one instruction counts imply — `sub_824531C8` runs 7,962,020
times on 43 instructions while `sub_82B22898` runs 40,160 on 583, and `sub_82B427D8` manages 4.
A **fourth gate** came out of it: the result must land where the harness can observe it.
`sub_824531C8` has zero stores and returns in `v0/v1/v12/v13/v59/v60`, none of which is in
`SHADOW_PRESERVED_VRS` or reachable by a `kReturn*` flag, so comparing it would check nothing on
eight million calls. Fixable by extending `ShadowReturn`; until then, register-only kernels are
out. First target **was** `sub_82B50380` (217 vec, 1,284 lines, no callees, 254,917 calls, 111
observable stores) — **and it fails gate 2, measured 2026-09-12.** Its address registers are
reassigned inside the function, so the window set cannot be derived from entry state: with
`r11 = 49600060` and `r3 = 4B399B80` at entry, the body's `ea = r11 + r3` would land at
`0x94999BE0`, outside guest range, and `r5 = E2E3F000` is not an address at all. The earlier
pass was reached by reading the *form* of the `ea` expressions rather than measuring their
operands — the same error as the `BUFPAIR` inference and the bit-offset reading, and the reason
the measurement was worth taking. Windowing it would need per-store instrumentation inside the
lifted body, not a hook that reads entry registers;
`sub_82B22898` (583 vec) is the heaviest but has five callees and a four-level subtree, so it is
not the place to start. One hazard is named there and not covered by Phase 0b: the
`stvlx128`/`stvrx128` unaligned store lowering writes partial vectors with opposite lane
orders, so a wrong translation fails **only** on unaligned inputs.

**Executed first, then heaviest.** The original order was heaviest first — `sub_82B22898`
(583), `sub_82B3A048` (557), `sub_82B02C30` and `sub_82B09288` (389 each) — and **only
`sub_82B22898` ran** in the 0a session. On `RwAudioCore Dac`, by vector instruction
count: `sub_82B22898` (583), `sub_82B50380` (217), `sub_82B42C98` (99), `sub_82B399D0`
(98), `sub_82B44D18` (84), then twelve smaller; full list in `docs/execution-trace.md`.
Recheck this once a skate/bail/replay trace exists.

1. Read the lifted form in `generated/skate3_recomp.*.cpp` — already on disk, no Ghidra.
2. Write native C++. Since RexGlue's lifted form is already the correct SIMDe/SSE
   lowering, this is largely a **readability rewrite**, not new arithmetic. Preserve the
   exact FTZ toggle points and the FMA-vs-separate-mul/add distinction.
3. Shadow-verify. **`ShadowCompare` needs extending first**: it diffs registers plus one
   contiguous ≤64 KB memory window, and its own comment says a function needing more
   should be compared on its output buffer instead. Build that buffer-output variant
   **once** and reuse it across all 40 kernels.

*Exit criterion, per kernel:* zero divergence on registers plus designated output buffer.
*Phase:* all 40 land. Be honest that the value here is readability and the harness, since
the recomp's audio was already exact.

### Phase 4 — Rust translation of the verified C++

Rolling queue fed by Phases 2 and 3 — each function can be translated as soon as *it* is
verified; no need to wait for either phase to finish. Two tiers:

- **Per-function bit-compare**, mainly for DSP kernels: identical inputs to the verified
  C++ and the Rust translation, **0 ULP** required. This is 0b's harness, extended.
- **End-to-end**: once enough graph exists, render a real scene and compare against that
  scene's `audio_dump_path` capture with `tools/mixdiff.py`.

*Exit criterion:* every ported function passes its bit-compare; a representative scene (one
ambience bed + one speech line + one music segment, mixed) matches bit-for-bit.

**Status 2026-09-11 — the queue path is ported, and NOT yet bit-compared.** `skate-audio-core`
holds `system.rs` (the producer's four paths) and `player.rs` (the three consumers, the FIFO and
the liveness scan), with 11 tests that pin record layouts, the FIFO state machine, the liveness
outcomes, the `EVENT_STOP` wipe, and the `fctidz` low-byte conversion.
**Tier 1 is met for four functions, 2026-09-11: every comparison of a complete session
replayed — 8,607 of 8,607, 0 disagreements, 0 skipped, 0 unreplayable** — the producer, `EVENT_SUBMIT`, `EVENT_PLAY` and
buffer-pair init (`buffers.rs`, an addition to the module list above).** Not via a C++ runner — the native bodies are written in terms of
`REX_LOAD_U32`/`REX_STORE_U32`, which exist only inside the 48,555-line
`generated/skate3_init.h`, and they sit in an anonymous namespace so no other TU can link them.
Instead the harness records the real comparisons it already performs
(`skate3_audio_vectors_path`) and the Rust replays them offline, which also satisfies the
project's preference for real inputs over generated ones.
Read `docs/shadow-harness.md` for what that green does **not** cover: 391 of 398
`EVENT_SUBMIT` passes verify one write vacuously, and all 1,173 query vectors had an empty FIFO,
so `packet_is_live`'s list-walk branch is untested by this data. The figure is real because four
negative controls fail correctly — and because the *first* control did **not** fail, which is
how the vacuous-pass problem was found at all.
One divergence is already known and deliberate, and the test suite pins it: the guest's
`fctidz` and Rust's saturating `as i64` disagree at exactly `2^63` (`0x00` against `0xFF`), so
the conversion is written branch for branch. A naive port would have been silently wrong there.
The ring's publish ordering also diverges deliberately — records first, offset last — which
leaves memory byte-identical and is therefore invisible to a single-threaded compare in either
direction.

**Status 2026-09-13 — 132 of the 140 verified (or thin) C++ bodies have a Rust translation and a
replay arm.** Before that day's porting, 109,099 recorded calls had replayed with zero failures
(the per-module counts are in `rust/skate-audio-core/README.md`). The same day added 22 bodies,
the 31 evaluator ops' generic arm, and `sub_82B43CC0`'s missing arm. Their window builders now
declare every read a replay needs, and all of them are unit-tested, but **none of them has replayed
yet**: sessions need an unlocked screen and no other skate3 instance. The recording is one session,
because the recorder gained `skate3_audio_vectors_per_function` (`AUDIO_VECTORS_PER_FN`): the
global cap otherwise fills with the hot functions before the rare ones are reached. `sub_82B305C0`
is never called in the boot profile, so it needs the scripted play profile.

The last eight are not transcription work, because each reaches a callee that has no verified C++
reference:

| body | the callee with no `.inc` |
|---|---|
| `sub_82B2DBA8`, `sub_82B42C98`, `sub_82B427D8` | `sub_82F52FB8` |
| `sub_82B238A8` | `sub_82B43340`, plus the two above |
| `sub_82B2F590` | `sub_82B2FF88` |
| `sub_82B470D0`, `sub_82B33780` | `sub_82B471D8`, `sub_82B472C0` |
| `sub_82B22898` | `sub_82473930`, `sub_82B41D58`, `sub_82B42510` |

Porting one of these means first giving that callee a native body verified under the shadow harness
(Phase 2's recipe), or porting it from the lifted code with nothing to compare it against.

**Update 2026-09-14, and a scope change.** The four one-callee blockers got native bodies (pending
verification), and all six bodies behind them now have Rust translations. So do `sub_82B42C98`,
`sub_82B427D8` and `sub_82B2DBA8`, and `sub_82B43340`'s C++ is written for `sub_82B238A8`.

The user narrowed the Rust side the same day: **the engine only needs the player character's
sounds, not other skaters, music or ambience.** The mixer core those sounds pass through (queue,
voices, per-voice DSP, gain, spatial, output) is shared by every sound, so the ports above stand.
Work that serves only music or ambience comes off the Rust queue. `sub_82B22898` (the
single-sideband frequency shift) and its five-helper chain are deferred until something shows a
player sound reaches it; the recomp's C++ keeps its whole-game goal.

**Replayed, 2026-09-14 (backlog1).** One boot-profile session recorded up to 300 vectors for each of
65 functions (`AUDIO_VECTORS_PER_FN`). All 34 expected shadow comparisons were clean, and the Rust
replay found **no failures in any function**. Eight functions did not replay because their window
builders left out memory the call reads. Those reads are now declared, and they wait for a second,
played session, together with the four functions a boot session never reaches.

**Caveat, measured in Phase 1:** two recomp sessions booted identically do not produce the
same capture. "Matches bit-for-bit" needs a reproducible scene, or a comparison inside one
process, before it can be tested. Open — risk 7.

### Phase 5 — containers and codec, Rust-only, fully parallel

> **Status 2026-09-12.** The codec bullet is **met by a different route than it names.** It asked
> for `tools/xma_decode.c`'s persistent-decoder pattern to be folded into the crate, and said that
> is what needs `libavcodec-dev`. This box has `libavcodec.so.62` and not its headers, so that tool
> cannot even be built here. Measuring the claim it rested on turned it over: the `ffmpeg` binary
> **can** keep decoder state across a stream's chunks, if each chunk is padded to a whole number of
> 2048-byte XMA2 packets before the chain is concatenated. Zero deficit on every context, byte
> identical across three different paddings, and byte identical to an independent decode of the one
> chunk that needs no prior state. The crate now owns the orchestration
> (`crates/skate-data/src/audio/ffmpeg.rs` in the engine) and the shell pipeline is gone.
> `docs/xma-transcode.md` carries the measurement and the three controls. A pure-Rust decoder is
> still the only way to drop the external binary, and `tools/xma_vectors.py` builds per-chunk
> vectors for checking one.

No dependency on the recomp build at all.

- Commit the `.mus` header and `next_segment_start` fixes already in the tree.
- `.mpf` sequencing, sections 0–3. Real-data first; do **not** grep on offsets.
- Fold `tools/xma_decode.c`'s persistent-decoder-instance pattern into the crate,
  replacing the shell-pipeline step. This is what actually needs `libavcodec-dev`
  (apt candidate 7:8.0.1) or the vendored-but-unbuilt FFmpeg in the SDK.
- `.abk`/`.bnk`, `.csi`, `BIG4`+`Viv4` — lowest priority, see non-goals.

*Exit criterion:* all three asset classes decode sample-exact through the crate's own API
rather than a shell pipeline, and `.mpf` sequencing is either decoded or explicitly
deferred with what is still open written down.

> **Phase 5 is met, 2026-09-12.** All three classes decode exactly through the crate's own
> orchestration, and `.mpf` sequencing is **decoded**, sections 0–3 included, with what is still
> open written down. The one thing the exit criterion asks for that is not literally true: the
> decode still calls the `ffmpeg` binary, because XMA2 is a hardware codec with no Rust decoder
> and this box has no `libavcodec` headers. The shell *pipeline* is gone; the external *binary*
> is not.

### Phase 6 — Rust engine integration

> **Status 2026-09-12: the first half of the exit criterion is met.** The engine reads a retail
> archive member, decodes it byte-exactly and plays it through a Bevy audio source; recording the
> output device while it played confirmed the samples reached the sound card (cross-correlation
> peak at the right lag, peak/mean 58.8 against 5.7 for a time-reversed control). What is **not**
> met: it does not play through the *ported graph* — it plays decoded PCM directly, because
> `scheduler.rs`, `xma.rs`, `dsp/` and `graph.rs` are unwritten — and nothing chooses *which*
> sound, because the metadata that maps a sound to a map or an event is undecoded.

Wire into `skate-3-rust-engine` as `crates/skate-data/src/audio/`, add host primitives,
drive playback from Bevy.

*Exit criterion:* the engine plays a real in-game sound through the ported graph, and a
capture of it matches the recomp's `audio_dump_path` for the same trigger, bit-for-bit.
Same caveat as Phase 4: the recomp's own captures differ between runs.

## 3. Critical path and parallelism

**Critical path:** Phase 1 → Phase 2 → Phase 4 → Phase 6.

**Fully parallel:** Phase 0a and 0b (start now, hours to days, and they reprioritise
everything downstream). Phase 5, the whole time.

**Partially parallel:** Phase 3 can start as soon as Phase 1's harness is proven, since it
touches functions disjoint from Phase 2's. Phase 4 is a rolling queue, not a gate.

## 4. Why this order

- **The trace (0a) runs immediately because it is free here** — the tracer is already in
  the binary. It no longer *gates* Phase 1 (that framing assumed no instrumentation
  existed anywhere), but there is no reason to skip a free measurement that reorders every
  later work queue.
- **The VMX128 probe (0b) is cheap for a structural reason**: RexGlue's lifted form is a
  complete, correct, already-on-disk lowering, and `rex/ppc/context.h` is self-contained
  enough to compile standalone. That turns "is Rust bit-exactness possible" from a
  question needing Ghidra plus a working recomp plus a play session into one answerable
  with a few hundred lines and no game data. Given `CLAUDE.md` calls this the single
  biggest risk in any estimate, resolving it before committing to 40 kernels is the
  highest information-gain-per-hour move available.
- **The instrumentation (Phase 1) is expensive and still goes first**, because every
  subsequent verification depends on it structurally. 0a and 0b do not reduce its cost or
  defer its necessity — they ensure the work it unlocks is spent on the right functions
  and is not chasing an impossible arithmetic goal.

## 5. VMX128 strategy — decided

**Mirror RexGlue's own SIMDe→SSE lowering, translated mechanically to
`core::arch::x86_64`. Not `std::simd`, not scalar-from-first-principles.**

1. **The lowering is already validated** across a large recompilation effort. Re-deriving
   it is redundant and riskier than transcribing it.
2. **The rounding of every multiply-add is load-bearing, in the direction the recomp computes it.**
   *Corrected 2026-09-13:* `vmaddfp`/`vmaddfp128` lower to `simde_mm_fmadd_ps`, but the recomp
   is built without `-mfma`, so SIMDe's fallback rounds the product and then the sum: **two**
   roundings. Scalar `fmadds` lowers to `std::fma` and stays single-rounding. The rule is:
   **translate `vmaddfp*` as `_mm_add_ps(_mm_mul_ps(a, b), c)`, `vnmsubfp*` as
   `_mm_sub_ps(c, _mm_mul_ps(a, b))`, and `fmadds` as `mul_add`.** LLVM will not auto-contract
   without fast-math, so the risk is a human writing the wrong one of the two.
   `docs/vmx128-exactness.md` rule 1 has the evidence, and how the probe missed it.
3. **FTZ is per-instruction-class and measurable.**
   `ctx.fpscr.{enable,disable}FlushModeUnconditional()` appears 999 + 136 times in
   `skate3_recomp.67.cpp` alone, before vector and scalar float ops respectively — VMX is
   always flush-to-zero, the scalar FPU follows the guest's FPSCR. Replicate at the same
   granularity by toggling MXCSR FTZ/DAZ around the vector sites. A single global mode
   will diverge on any kernel mixing vector and scalar float work, and several do.
4. **BE↔LE lane order is mechanical**: `simde_mm_shuffle_epi8(..., VectorMaskL)` →
   `_mm_shuffle_epi8` with the identical mask, ported once.
5. **Target x86_64 specifically.** `std::simd` is nightly and abstracts away exactly the
   bit-level control exactness needs. ARM64 bit-exactness is a materially larger problem —
   see non-goals.

**The 0b spike: done, and it validated this strategy.** Mirroring RexGlue's lowering was
the right call — the whole surface reduces to intrinsics Rust has 1:1, RexGlue helpers
that are pure integer code, and two libm calls. `vrsqrtefp` is notably *not* a hardware
estimate: RexGlue implements it as a 32-entry integer table lookup, so it ports as data.
Full results in `docs/vmx128-exactness.md`.

Note this is *not* a doctrine violation. The rule against synthetic tests is about
container and format structure, where real data exposes distributional surprises. Here the
question is "does this hardware operation match that one," and denormals are precisely what
gameplay will *not* reliably exercise. Adversarial vectors give more coverage per hour.

## 6. Rust architecture

**`skate-audio-formats`** (exists, extend) — containers only, `#![forbid(unsafe_code)]`,
no codec math. Add `.mpf` when Phase 5 lands. The only piece the recomp has no use for.

**`skate-audio-core`** (**started 2026-09-11**: `lib.rs`, `system.rs`, `player.rs`, 11 tests;
`scheduler.rs`, `xma.rs`, `dsp/` and `graph.rs` not yet written) — ported graph, scheduler,
queue, DSP. Modules mirror `docs/rw_audio_structs.h`:

Guest structures are modelled as **byte-addressed big-endian accessors over a `&mut [u8]`**
(`Guest`), not as idiomatic Rust structs. These are recovered layouts with asserted offsets,
and Phase 4's per-function criterion compares bytes against the verified C++, so a
byte-addressed view makes that comparison direct instead of routing it through a serialisation
step that could hide a discrepancy of its own. Offsets are asserted at compile time with
`const _: () = assert!(...)`, mirroring `docs/rw_audio_structs_check.c`.

Two callees are **closure parameters**, not ports: `sub_82B3C930` (`EVENT_STOP`'s decoder
teardown, four indirect calls) and `sub_82B29018` (`EVENT_PLAY`'s restart branch, two indirect
calls plus a critical section). Neither is portable, and the first is precisely why `EVENT_STOP`
has no comparable path under the harness.

- `system.rs` — `rw_system`: command ring, scheduler buckets, lock indirection. Host
  primitives, from the kernel-import survey: a **recursive** mutex (the fallback is
  `RtlEnterCriticalSection`, which is re-entrant), a spinlock, and the ring's
  store-record-then-publish-offset discipline with release/acquire ordering.
- `player.rs` — `rw_player`, `PacketPlayer` events, the FIFO.
- `scheduler.rs` — two-bucket tick, per-plug-in profiling toggle, mid-tick self-removal
  (`scheduler + 0x4C`).
- `xma.rs` — paired input/output ring protocol against a decoder **trait**. Desktop
  backing uses the persistent-decoder pattern, never per-chunk restarts: that is exactly
  the 64-sample MDCT overlap loss a naive port reintroduces.
- `dsp/` — one file per plug-in family, each a mechanical translation of one verified C++
  function, `unsafe` scoped tightly to intrinsic calls, each citing the source PPC
  mnemonic the way the lifted C++ does. That convention is what keeps the translation
  auditable line-by-line.
- `graph.rs` — instantiation and wiring driven by the descriptor metadata
  `tools/rw_audio_extract.py` already recovers, so graph shape is not hand-guessed.

**Drop-in:** `crates/skate-data/src/audio/`, both as path dependencies; the engine supplies
the device backend behind a trait `skate-audio-core` defines but does not implement.

## 7. Verification without the macOS machine

Nothing here needs it. The shadow harness always was a same-machine mechanism — it was
just never wired up here. The `audio_dump_path` oracle is captured on this box from this
box's data. The per-function bit-compare needs no game session at all.

The two unlanded bugs are documented as not reproducing on macOS either (out-of-order
ARM64). Their *fixes* are derived from the code, not from a repro, so landing them under
the shadow harness is itself verification. What stays genuinely out of reach is confirming
their **root causes** on real QCS8550/ARM64 hardware. That remains open and hardware-gated;
this plan does not pretend to close it.

## 8. Risks, ranked, each with its retiring measurement

1. ~~**VMX128 Rust bit-exactness.**~~ **Retired by 0b: GO.** 45/45 operations
   bit-identical. Residual, both narrow: (a) `vexptefp128`/`vlogefp128` route through
   libm and match only because Rust and glibc share a symbol on this platform — keep them
   in the per-kernel bit-compare permanently; (b) NaN payload ordering on commutative
   float ops, cookbook rule 4. Whole-kernel composition is still unproven and is Phase 3
   work, but no longer a risk to the plan's viability.
2. ~~**The `audio_dump_path` tap is new RE work of unknown-until-attempted cost.**~~ **Retired
   in Phase 1.** The mix point is the `XAudioSubmitRenderDriverFrame` import, and the tap is
   one small file. Its one real cost was a SIGFPE from unmasked host FP exceptions on the
   audio worker thread.
3. **`ShadowCompare`'s window diff does not fit DSP output buffers** — its own comment says
   so. Retire: build the buffer-output variant at the start of Phase 3 and prove it on the first kernel before assuming it generalises to the other 39. Partly done
   in Phase 1: it now takes a list of windows, up to 64 KB in total. A kernel writing more
   still needs a buffer-output variant.
4. **`.mpf` sequencing undecoded.** Blocks interactive music as a feature, not bit-exact
   playback of a given segment. Retire: Phase 5. This is exactly the field where three
   prior coherent stories were all wrong; no shortcuts.
5. **0a's number could still mislead** — it is address-range filtered and thread-unaware.
   Retire: cross-check against which functions actually produce shadow comparisons in
   Phases 2–3. A "hot" function that never shows one means the filter is off. Already
   visible in the first trace: seven vector functions inside the audio window were first
   called on the render thread.
6. **Disk creep** over dozens of relinks (25 GB free; `out/build/linux-release-jammy` is
   363 MB, `rexglue-sdk/out` 1.1 GB). Retire: watch `df -h`. Cheap to check.
7. **The mix is not reproducible run to run.** Two sessions booted the same way differ in
   22–28% of aligned submits, starting with values near 1e-15 and growing to full scale.
   This blocks bit-for-bit comparison across sessions (Phases 4 and 6), not per-function
   verification. Retire: find the source — thread timing, random variation or streaming —
   before relying on any cross-session capture comparison.

## 9. Non-goals, deliberately

- **ARM64/macOS bit-exactness for the Rust port.** The x86_64 intrinsic strategy is
  deliberately not portable; NEON equivalence would roughly double the numerics
  verification surface for a target nobody ships to yet.
- **Extending Ghidra's SLEIGH for VMX128.** Already decided correctly in
  `docs/decompilation-status.md`; reuse that decision.
- **Reinstalling Ghidra/JDK at all, for now.** `generated/` already holds a complete
  correct lifted form for *every* one of the 1,694 functions, not just the 52 that need
  it. Ghidra's C is nicer to read but strictly optional. Escalate only if reading the
  lifted form proves too slow — same cheap-path-first principle the VMX128 call used.
- **`.abk`/`.bnk`, `.csi`, `BIG4`+`Viv4`.** No evidence they are on the critical path;
  ambience, speech and music cover the overwhelming majority of in-game audio. Revisit
  only if a specific missing sound traces to one.
- **A general-purpose XMA/EAAC toolkit.** Build what the two crates need; resist scope
  creep toward hypothetical other consumers.
- **Root-causing the two recomp bugs on QCS8550/ARM64 hardware.** Land the C-level fixes;
  leave root-cause pinning explicitly open rather than chasing an unavailable repro.

## Files that matter most

| file | why |
|---|---|
| `skate3recomp-dev/CMakeLists.txt` | where `recomp/src/skate3_audio_*.cpp` get wired in (Phase 1) |
| `recomp/src/skate3_audio_shadow.cpp` / `.h` | the harness; needs the buffer-output extension for Phase 3 |
| `recomp/src/skate3_audio_native.cpp` | the one existing unverified function, and the pattern every later one follows |
| `skate3recomp-dev/generated/skate3_recomp.*.cpp` | ground truth for every audio function, VMX128 included |
| `docs/rw_audio_structs.h` | the layouts both the C++ and the Rust structs are written against |
| `docs/environment-linux.md` | what is true of *this* machine and not of the docs' macOS one |
