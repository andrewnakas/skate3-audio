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

**0a. Guest execution trace.** The tracer is already compiled into
`out/build/linux-release-jammy/skate3`. No code change, no rebuild.

```sh
./skate3 --game_data_root=<game> --skate3_install_tu=<TU> \
         --skate3_trace=true --skate3_trace_mode=first
```

Intersect the traced address set with the 1,694-function audio corpus.

*Exit criterion:* a number — "N of 1,694 functions execute during a representative
session covering menu, a skate run, and a crash/replay." It is an **upper bound**:
address-range filtered, not thread-filtered, breadth not frequency. Use it to order
Phases 2 and 3 by what is actually reachable.

**0b. VMX128 pathfinder spike. DONE — result GO.** See `docs/vmx128-exactness.md`;
reproduce with `probe/vmx128/run.sh`.

45 of 45 operations bit-identical across 56,880 lane comparisons, covering every distinct
lowering family in the 76-mnemonic surface, under both MXCSR flush-to-zero states.

The spike was done per *operation* rather than per kernel: each of the five heaviest
kernels calls between three and nine other guest functions, so a standalone link needs
stubs, whereas the go/no-go question is answered more decisively and more cheaply at the
instruction level — and that is also the form the cookbook wanted.

One rule beyond those anticipated: **commutative float ops are not NaN-commutative**, and
GCC's operand ordering is an unstable artifact of register allocation. That is the only
divergence found and it is confined to NaN inputs. Rule 4 in the cookbook.

Two corrections to what this section assumed: `sub_82B22898` has **zero** FMA sites (it is
the largest kernel, not an FMA-heavy one — those are `sub_82B02C30`/`sub_82B09288`), and
the build needs **`-std=c++23`**, not C++20.

Neither blocks Phase 1. Run them while Phase 1's build is going.

### Phase 1 — instrumentation in this tree, harness proven (critical path, step one)

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

### Phase 2 — struct layouts and scalar plug-in logic, native C++

In Phase 0a frequency order where available, else call-graph order:

- Command queue producer/consumer (`sub_82B28A00`, `sub_82B28B78/C18/CC0`,
  `sub_82B48530`) — land the ordering fix from `docs/command-queue.md` natively.
- Scheduler tick (`sub_82B48A50`, `sub_82B482F8`, `sub_82B48440`).
- Buffer-pair init/measure (`sub_82B7F828`, `sub_82B7F998`, `sub_82B7F8A8`) — land the
  fix from `docs/buffer-size-bug.md`.
- Scalar plug-in math: filters, panners, submix, gain/dynamics — whatever 0a shows runs.

Per function: read, write native C++, shadow-verify to zero divergence, promote. Because
a hook is now a TU compile plus a relink rather than a full rebuild, run this as a **tight
one-function-at-a-time loop**, not batched per build cycle.

*Exit criterion, per function:* zero divergence over a session exercising its path.
*Phase:* every function 0a calls hot is native and promoted; both known bugs landed.

### Phase 3 — VMX128 kernels, native C++

Heaviest first: `sub_82B22898` (583 instrs), `sub_82B3A048` (557), `sub_82B02C30` and
`sub_82B09288` (389 each).

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

*Exit criterion:* every ported function passes its bit-compare; a representative scene
(one ambience bed + one speech line + one music segment, mixed) matches bit-for-bit.

### Phase 5 — containers and codec, Rust-only, fully parallel

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

### Phase 6 — Rust engine integration

Wire into `skate-3-rust-engine` as `crates/skate-data/src/audio/`, add host primitives,
drive playback from Bevy.

*Exit criterion:* the engine plays a real in-game sound through the ported graph, and a
capture of it matches the recomp's `audio_dump_path` for the same trigger, bit-for-bit.

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
2. **FMA is semantically load-bearing.** `vmaddfp`/`vmaddfp128` lower to
   `simde_mm_fmadd_ps` — a genuine single-rounding fused multiply-add. The rule:
   **translate `vmaddfp*` to `mul_add`/`_mm_fmadd_ps`; translate a `vmulfp128` followed by
   a separate `vaddfp128` as two separate ops, never let them collapse.** LLVM will not
   auto-contract without fast-math, so the real risk is a human writing `a*b+c` for what
   was two instructions. Guard with convention and a lint, not by hoping the default holds.
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

**`skate-audio-core`** (new) — ported graph, scheduler, queue, DSP. Modules mirror
`docs/rw_audio_structs.h`:

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
2. **The `audio_dump_path` tap is new RE work of unknown-until-attempted cost**, not the
   drop-in the docs' phrasing suggests. Retire: time the actual locate-and-hook work in
   Phase 1; do not estimate it from the other files' line counts.
3. **`ShadowCompare`'s window diff does not fit DSP output buffers** — its own comment says
   so. Retire: build the buffer-output variant at the start of Phase 3 and prove it on the
   first kernel before assuming it generalises to the other 39.
4. **`.mpf` sequencing undecoded.** Blocks interactive music as a feature, not bit-exact
   playback of a given segment. Retire: Phase 5. This is exactly the field where three
   prior coherent stories were all wrong; no shortcuts.
5. **0a's number could still mislead** — it is address-range filtered and thread-unaware.
   Retire: cross-check against which functions actually produce shadow comparisons in
   Phases 2–3. A "hot" function that never shows one means the filter is off.
6. **Disk creep** over dozens of relinks (25 GB free; `out/build/linux-release-jammy` is
   363 MB, `rexglue-sdk/out` 1.1 GB). Retire: watch `df -h`. Cheap to check.

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
