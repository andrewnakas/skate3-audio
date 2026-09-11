# This machine — what differs from the docs

`CLAUDE.md`, `docs/REPRODUCING.md` and `docs/running-the-recomp.md` were written on an
8 GB macOS M1. **This is a different machine**, and several statements in those documents
are true there and false here. Everything below was measured on 2026-09-11, not inherited.

Read this before trusting a path, a build instruction, or a "trap" from the other docs.

## The machine

Linux, 12 cores, 30 GB RAM, 25 GB free on `/`. `rustc`/`cargo` **1.98.1** in `~/.cargo/bin`
(installed 2026-09-11). `gcc` 15.2. `python3` 3.14. `ffmpeg` CLI 8.0.1.

The macOS notes about `polite_build.sh` throttling on low memory, and about a build and a
play session not being able to coexist on 8 GB, **do not apply**. Full parallel builds are
fine.

## Paths

| what | where |
|---|---|
| this repo | `/home/nakas/Documents/sk8Audio` |
| recomp | `/home/nakas/Documents/skate3/skate3recomp-dev` (HEAD `aa671f5`, branch `diag/white-fallback-attribution`) |
| built binary | `…/out/build/linux-release-jammy/skate3` |
| lifted C++ | `…/skate3recomp-dev/generated/` — 289 MB, 113 `skate3_recomp.*.cpp` |
| game data | `/home/nakas/Documents/skate3/freeskate/runtime/game/data/audio/` |
| disc image | `/home/nakas/Documents/skate3/skate3.iso` |

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

This is the single most important difference, because it moves work onto the critical path.

- `src/` contains **no** `skate3_audio_*.cpp`. `git log --all -- '*audio*'` is **empty** on
  every branch.
- The built binary has **no** `audio_dump_path`, **no** `audio_stats`, **no** `xma_stats`.
- It **does** have the guest tracer compiled in: `skate3_trace`, `skate3_trace_mode`,
  `skate3_trace_arm`, `skate3_trace_capacity`, `skate3_trace_dump_delay_ms`.
- The SDK source has an `audio_stats` cvar
  (`third_party/rexglue-sdk/src/audio/sdl/sdl_audio_driver.cpp:38`), but the binary
  predates even that.
- Host audio lives in the SDK, not the game: `third_party/rexglue-sdk/src/audio/`
  (`audio_system`, `audio_driver`, `xma_context`, `xma_decoder`, `xma_register_file`) and
  `src/kernel/xboxkrnl/xboxkrnl_audio_xma.cpp`.

**Consequences.** The guest trace is free — run it today, no rebuild. The bit-exact
reference capture is **not** available: `audio_dump_path` has to be written, and no source
for it exists in this tree or its history, so it is new reverse-engineering work rather
than a drop-in. `recomp/src/*.cpp` in this repo are the drop-in sources for the probe,
shadow harness and native functions.

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

No `TU_*` package file exists on this machine. The TU patch appears to be **already staged**
as `default.xexp` in the game directory
(`freeskate/runtime/game/default.xexp`, and in `out/build/linux-release-jammy/game/`).
`SKATE3_INSTALL_TU` is read as an environment variable at
`src/skate3_app_common.cpp:658` and `src/skate3_title_update_installer.cpp:851`.

**Unconfirmed.** Verify on the first run with audio stats enabled rather than assuming —
the failure mode is designed to look like something else.
