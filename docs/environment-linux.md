# This machine — what differs from the docs

`CLAUDE.md`, `docs/REPRODUCING.md` and `docs/running-the-recomp.md` were written on an
8 GB macOS M1. **This is a different machine**, and several statements in those documents
are true there and false here. Everything below was measured on 2026-09-11, not inherited.

Read this before trusting a path, a build instruction, or a "trap" from the other docs.

## The machine

Linux, 12 cores, 30 GB RAM, 25 GB free on `/`. `rustc`/`cargo` **1.98.1** in `~/.cargo/bin`
(installed 2026-09-11). `gcc` 15.2. `python3` 3.14. `ffmpeg` CLI 8.0.1.
The recomp is built with **clang++-20** (`CMAKE_CXX_COMPILER` in the jammy build cache).
There is no unversioned `clang++`, so `which clang++` finding nothing does not mean clang
is absent.

The macOS notes about `polite_build.sh` throttling on low memory, and about a build and a
play session not being able to coexist on 8 GB, **do not apply**. Full parallel builds are
fine.

## Paths

| what | where |
|---|---|
| this repo | `/home/nakas/Documents/sk8Audio` |
| recomp | `/home/nakas/Documents/skate3/skate3recomp-dev` (was HEAD `aa671f5` on `diag/white-fallback-attribution`; audio work is on `audio/phase1-harness`) |
| built binary | `…/out/build/linux-release-jammy/skate3` |
| lifted C++ | `…/skate3recomp-dev/generated/` — 289 MB, 113 `skate3_recomp.*.cpp` |
| game data | `/home/nakas/Documents/skate3/freeskate/runtime/game/data/audio/` |
| disc image | `/home/nakas/Documents/skate3/skate3.iso` |
| `linux-release` | `…/out/build/linux-release` is a **symlink to `linux-release-jammy`** — the same binary and the same `librexruntime.so`. Other projects' launchers run `linux-release/skate3` (skate3loader does), so every rebuild here changes the binary they run |
| release install | `/home/nakas/Documents/skate3/Skate3Recomp-Linux` (Jul 24) — what `freeskate` launches unless told otherwise |
| game root for runs | `freeskate/runtime/game` — a symlinked shadow of `Skate3Recomp-Linux/game`; checked stock, no map overrides |

All retail audio data is present: `ambience.big`, `ambienceresident.big`, `wheels.big`,
`grains.big`, `post.big`, `audiofiles.big`, per-language speech under `english/` etc., and
`music/` with all three `.mus` plus their `.mpf`.

## Not installed

**Ghidra, and no JDK.** So `docs/REPRODUCING.md` section 3 cannot run as written.

This matters less than it looks. `generated/` already holds a complete, correct RexGlue
lifted form for **every** one of the 1,694 audio functions — not only the 52 Ghidra cannot
decode. Ghidra's decompiled C is more pleasant to read, but it is strictly optional.
Read the lifted form and only stand up the Ghidra pipeline if that proves too slow.

**`libavcodec-dev`.** The apt candidate is `7:8.0.1-3ubuntu2`. FFmpeg is also vendored at
`third_party/rexglue-sdk/thirdparty/FFmpeg` but is **not built** — no `libavcodec.a` or
`.so` exists in the tree. Either route works for `tools/xma_decode.c`; neither is done.

## The audio instrumentation is absent from this recomp checkout

> **Update 2026-09-11:** Phase 1 added it, on recomp branch `audio/phase1-harness`
> (`e581969`), and the jammy binary is built from that branch. This section describes the
> checkout before that commit. Results are in `docs/shadow-harness.md`.

This is the single most important difference, because it moves work onto the critical path.

- `src/` contains **no** `skate3_audio_*.cpp`. `git log --all -- '*audio*'` is **empty** on
  every branch.
- The build has **no** `audio_dump_path` and **no** `xma_stats`. It **does** have
  `audio_stats`: the SDK is linked as `librexruntime.so`, and its cvars live in that
  library, not in the `skate3` executable. An earlier version of this file checked only
  the executable and reported `audio_stats` missing.
- It has the guest tracer's **cvars and controller** compiled in (`skate3_trace`,
  `skate3_trace_mode`, `skate3_trace_arm`, `skate3_trace_capacity`,
  `skate3_trace_dump_delay_ms`) but **not its recording hook**. An earlier version of this
  file said the tracer was compiled in and a trace was free; that was wrong. The hook is a
  local edit to `generated/skate3_init.h`, and this checkout's header was stock: the stock
  binary has **zero** per-function `_skate3_seen` statics, so an armed trace would have
  dumped an empty file. See "Running the guest trace" below.
- `audio_stats` is defined at
  `third_party/rexglue-sdk/src/audio/sdl/sdl_audio_driver.cpp:38` and is in the built
  runtime library. Grep `librexruntime.so`, not `skate3`, for any SDK cvar.
- Host audio lives in the SDK, not the game: `third_party/rexglue-sdk/src/audio/`
  (`audio_system`, `audio_driver`, `xma_context`, `xma_decoder`, `xma_register_file`) and
  `src/kernel/xboxkrnl/xboxkrnl_audio_xma.cpp`.

**Consequences.** The guest trace is **not** free: it needs the hook applied and a rebuild,
measured below at a little over three minutes. The bit-exact
reference capture is **not** available: `audio_dump_path` has to be written, and no source
for it exists in this tree or its history, so it is new reverse-engineering work rather
than a drop-in. `recomp/src/*.cpp` in this repo are the drop-in sources for the probe,
shadow harness and native functions.

## Running the guest trace (measured 2026-09-11)

Tooling is in `probe/trace/`.

1. **Apply the hook.** `probe/trace/trace_hook.py apply` inserts the macro documented at the
   top of `src/skate3_guest_trace.cpp` into `generated/skate3_init.h`.
2. **Rebuild.** That header is included by **127 objects** (111 generated, 16 in `src/`).
   `ninja -j10 skate3` in `out/build/linux-release-jammy`: **195 s wall**, peak **820 MB**
   per compile, binary 89.8 → 100.1 MB. This is the real cost of a header touch here, and
   the first build timing taken on this machine.
3. **Check it took.** `nm skate3 | grep -c _skate3_seen` gives 47,889 with the hook and 0
   without. **Do not grep `objdump` for `call <skate3_trace_enter>`** — it finds 0 either
   way, because the recomp is built with the large code model and the call goes through a
   register.
4. **Run** `probe/trace/run_trace.sh LABEL [MACRO]` and **analyze** with
   `probe/trace/analyze_trace.py`, against the corpus from `probe/trace/corpus.py`.

What the arm modes actually do, read from `ControllerMain`: `boot` arms at startup and dumps
`skate3_trace_dump_delay_ms` after gameplay context 1, capped at 120 s; `gameplay` arms at
gameplay context 1 and dumps after the same delay; `macro-final` needs a demo-path macro;
`manual` arms and **never dumps** — there is no other dump path, not even at exit. So one
trace covers at most two minutes past reaching gameplay.

The dump has a thread column. In `first` mode it is the thread of the **first** call only,
so it is a hint rather than a filter.

**`ring` mode was a crash generator until 2026-09-11.** The recorder dereferences r3, r4
and r5 looking for strings, and its readable window ran to `0x80000000` — which includes
the guest **stack** band (`0x70030000`..`0x707BFB20`). Stacks are 1 MB allocations in a
sparsely committed view where reserved pages are `PROT_NONE`, so one page past a live
stack faults on read. `first` mode reads once per function and three sessions never hit
it; `ring` reads on every call and faulted 217 ms after arming. Fixed: the window stops
at `0x60000000` and `ring` skips string capture. Verified by re-running the same ring
session to completion with zero faults.

**`--skate3_trace_dump_on_crash=true` writes the trace from the crash handler**, so a run
that faults before any dump trigger still leaves its buffer (measured: 262,144 entries on
a guest fault). It catches guest faults and aborts — not SIGKILL, which is uncatchable, so
a killed session still writes nothing. Off by default: the dump is not async-signal-safe.

**Stopping a session.** The game **ignores SIGTERM** — it was still running 15 s later —
so close the window or `pkill -KILL -x skate3`. Once `skate3 trace: DUMPED` is in the log
the trace file is complete.

**Current state, 2026-09-11:** the hook is **applied** in `generated/skate3_init.h` and the jammy binary carries it — and so does `out/build/linux-release/skate3`, which is the same
file through a symlink. An earlier version of this line called it stock; it never was. It was left in for a second, human-played trace. The same binary also carries the Phase 1 audio code and the input-script harness. A peer
session's skate3loader run crashed on this build at 15:55 on 2026-09-11, not yet attributed;
coordinate before relinking while another session is testing.

**Undo.** `trace_hook.py remove` restores the header byte-for-byte, verified against the stock
file. Its mtime is new, so the next build recompiles the same 127 objects back to stock.
Codegen also regenerates the header and drops the edit. The hook is cheap to leave in while
disarmed — two global loads and a not-taken branch per guest call — but a binary carrying it
is not the stock binary, which matters for any timing comparison.

## The hook rebuild trap does not apply here

`CLAUDE.md` says:

> **Adding a hook forces a full rebuild.** `generated/skate3_hooked_funcs.h` is included by
> `skate3_init.h`, which every translation unit includes. One new hook rebuilds everything.

and therefore tells you to batch native functions per build cycle.

**That mechanism does not exist in this checkout.** There is no
`generated/skate3_hooked_funcs.h` and no `tools/gen_hooked_funcs.sh`, and
`generated/skate3_init.h` includes no such header. Hooking here is **link-time weak-symbol
override**:

```c
// third_party/rexglue-sdk/include/rex/ppc/context.h:53
#define REX_WEAK_FUNC(x) __attribute__((weak, noinline)) REX_FUNC(x)

// generated/skate3_init.h:63   (non-Apple branch)
#define DEFINE_REX_FUNC(name) \
  __attribute__((alias("__imp__" #name))) REX_WEAK_FUNC(name); \
  REX_EXTERN(__imp__##name)
```

Every generated `sub_XXXXXXXX` is a **weak alias** to a strong `__imp__sub_XXXXXXXX`.
Defining `extern "C" REX_FUNC(sub_XXXXXXXX) { … }` in any `.cpp` in the `skate3` target
wins at link time. This is already how the existing native work is done —
`src/skate3_native_scene.cpp:10792` is `extern "C" REX_FUNC(sub_82802A00) {`, and there
are 103 `REX_FUNC` uses across `src/`.

Verified with `nm` against the built binary:

| symbol | binding | meaning |
|---|---|---|
| `sub_82802A00` | `T` | natively overridden, override won |
| `sub_82B22898` | `W` | still the lifted VMX128 kernel |
| `__imp__sub_82802A00` | `T` | the original **survives** alongside the override |
| `__imp__sub_82B22898` | `T` | original directly callable |

80 guest functions are already strongly overridden; 47,572 remain weak.

**Two consequences.** Adding a native audio function costs **one TU compile plus a
relink**, not a full rebuild — so drop the batching rule and run a tight
one-function-at-a-time shadow-verify loop. (Do still cost the relink: it is an 89 MB binary
over 289 MB of generated code, not free.) And the shadow harness needs **no codegen or
registration at all**: a wrapper defined as `REX_FUNC(sub_X)` can call
`__imp__sub_X(ctx, base)` to run the true original, keep that result, run the candidate
against a rewound context copy, compare, discard.

Treat the `CLAUDE.md` trap as **version-specific to the macOS tree**, not wrong in general.
That machine may carry newer codegen that introduced the header.

### But a NEW source file is silently ignored (2026-09-11)

The cheap-relink rule above holds for a hook added to a translation unit the build already
knows about. It does **not** hold for a new file, and the failure mode is silent.

`CMakeLists.txt` carries an **explicit source list** (around line 256, every `src/*.cpp` named
individually) — not a `file(GLOB)`. Add a new TU, build, and `ninja` prints nothing unusual and
**exits 0**. Nothing compiles it, no object file appears, and any `extern "C" REX_FUNC(...)`
overrides in it stay weak `W`, so the binary behaves exactly as before.

That cost a wasted session here. A counting-hook TU for the Phase 3 kernels was written, built
"successfully", and a session run against it — and the only reason the result was not read as
"these kernels are never called" is that the symbols were checked rather than the exit code:

```
overrides now strong: 0/4 sampled          # and no .o file for the new TU
```

**So check the artifact, never the exit status.** After listing the file, the same two checks
pass unambiguously: the object file exists, and 15 of 15 symbols report strong `T`.

Two corrections to costs quoted elsewhere. Adding a source file does **not** trigger the
"reconfigure plus 261 build steps" that `docs/shadow-harness.md`'s table implies: measured here
it was **11 steps in 8 s**, because only `main.cpp`, `rex_app.cpp` and the new TU needed
rebuilding. And the reconfigure is automatic — `ninja` re-ran CMake itself, no manual configure
step was needed.

## The VMX128 kernels are readable right now

`CLAUDE.md` calls VMX128 exactness "the single biggest risk in any effort estimate." It is
more approachable than that implies, because **RexGlue already solved the lowering and the
result is on disk**.

`sub_82B22898` (`FrequencyShiftSsb`, the heaviest at 583 VMX128 instructions) is at
`generated/skate3_recomp.67.cpp:11489` as `DEFINE_REX_FUNC(sub_82B22898) { … }`. Each
instruction is lowered to SIMDe/SSE intrinsics with the original mnemonic in a comment
above it:

```cpp
// stvx128 v125,r1,r12
ea = (ctx.r1.u32 + ctx.r12.u32) & ~0xF;
simde_mm_store_si128((simde__m128i*)REX_RAW_ADDR(ea),
    simde_mm_shuffle_epi8(simde_mm_load_si128((simde__m128i*)ctx.v125.u8),
                          simde_mm_load_si128((simde__m128i*)VectorMaskL)));
```

Note `VectorMaskL` — that is the BE↔LE lane reversal, applied on every vector load/store.

Two further measurements that shape the Rust translation:

- `vmaddfp`/`vmaddfp128` lower to `simde_mm_fmadd_ps` — a genuine single-rounding fused
  multiply-add, **not** multiply-then-add.
- `ctx.fpscr.{enable,disable}FlushModeUnconditional()` is emitted **per instruction
  class**, not once per function: 999 `disable` and 136 `enable` in file 67 alone. That
  matches real Xenon semantics — VMX is always flush-to-zero, the scalar FPU follows the
  guest's configured mode. A single global FTZ choice will diverge on any kernel mixing
  vector and scalar float work, and several do.

SIMDe here is configured for x86 (`avx.h`, `sse.h`, `sse4.1.h`) and this CPU has AVX2,
FMA3 and SSE4.x natively, so a bit-exact hardware-backed probe needs no emulation.

## The title update appears pre-staged

`docs/running-the-recomp.md` records an hour lost to launching without
`--skate3_install_tu`: the game sits on an installer overlay, the main guest thread blocks
holding a critical section, and audio reports 100% silent submits with zero XMA voices,
which looks exactly like total audio failure.

No `TU_*` package file exists on this machine. Both payloads are staged as symlinks in
`freeskate/runtime/game` and match `IsTitleUpdateInstalled`'s size and SHA-256
(`default.xexp` 1,701,888 bytes, `eb9ef910…`; `EAWebkit.xexp` 4,096 bytes, `5d4a308d…`), so
that check passes. On Linux a failing check runs the installer blocking; the empty-to-ask
overlay described below is the `__APPLE__` path. The TU patch appears to be **already staged**
as `default.xexp` in the game directory
(`freeskate/runtime/game/default.xexp`, and in `out/build/linux-release-jammy/game/`).
`SKATE3_INSTALL_TU` is read as an environment variable at
`src/skate3_app_common.cpp:658` and `src/skate3_title_update_installer.cpp:851`.

**Confirmed 2026-09-11.** Launched with no `SKATE3_INSTALL_TU`, the game reached gameplay
13 s after launch, and the trace captured music, sound-bank and speech loads. That rules
out the installer stall. This binary has no audio stats, so actual audio output was not
measured that way.
