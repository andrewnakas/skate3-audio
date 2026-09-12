# Brief: porting one Skate 3 audio function to native C++

You are given ONE guest function, `sub_XXXXXXXX`, as RexGlue's lifted C++ (one statement per
PowerPC instruction, the mnemonic in a comment above each). Your job is to write a readable
native rewrite of it, plus a window builder that names every byte it writes, in a single file:

    recomp/src/audio_ports/sub_XXXXXXXX.inc         (in the sk8Audio repo; never the recomp tree)

and a short note:

    probe/ports/notes/sub_XXXXXXXX.md

The rewrite is verified by a shadow harness that runs the ORIGINAL first, rewinds the declared
windows, runs YOUR body on the rewound copy, and diffs the ABI-preserved registers, the named
result registers and every declared window byte for byte. A wrong body cannot damage the game
as long as every byte it writes is inside a declared window. A write outside the windows is
never rewound and reaches the live game -- that is the one thing you must not do.

## Exact semantics, non-negotiable

- Reproduce the ORIGINAL, bug for bug. No fixes, no "obvious" improvements, no reordering of
  stores. Bug 1 (the command-queue publish order) stays as it is.
- Preserve store order. Do not hoist a load across a store that could alias it. When the
  original reloads a value it just stored, reload it.
- Integer widths: the lifted form keeps 64-bit registers. A result compared in `r3` is compared
  as ALL 64 bits, so produce the same 64-bit value the original leaves (`ctx.r3.u64 = a + b`
  where both were zero-extended u32 loads is NOT the same as a 32-bit add). Use the same
  `.u32`/`.s32`/`.u64` accesses the lifted body uses for any register you leave behind.
- Float: keep `lfs`/`stfs` single-precision round trips; `fctidz`/`fctiwz` edge cases (NaN,
  values past 2^63, the `>` versus `>=` at exactly 2^63) branch for branch, as in
  `TruncatedLowByte` in recomp/src/skate3_audio_native.cpp. FMA only where the lifted line is
  `fmadd`/`fmsub`/`vmaddfp*`; a `mul` followed by `add` stays two operations.
- `ctx.fpscr.enableFlushModeUnconditional()` / `disableFlushModeUnconditional()` calls stay at
  the same points relative to the float work. Native float math runs under the guest's mode;
  do NOT mask exceptions around it. Only host-only work (logging) gets masked, and you should
  not be logging.
- VMX: use the same SIMDe intrinsics as the lifted line, the same `VectorMaskL` shuffles on
  every vector load/store, and `stvlx128`/`stvrx128` in the same two-loop byte form.
- Callees: call them through `GuestCall(ctx, base, sub_YYYYYYYY, arg0, arg1, ...)` from
  `skate3_audio_port.h`, on the live context, and read the result from `ctx.r3` (or `f1`)
  after. Never call `__imp__sub_YYYYYYYY` directly. Volatile registers are clobbered by the call
  exactly as on the real machine; your body must not depend on them afterwards.
- The function's OWN stack frame (`stwu`, the `__savegprlr` spills, `-8(r1)` etc.) does not need
  reproducing and is not windowed. Callee-saved registers you clobber must be restored, because
  r13-r31, f14-f31 and v14-v31/v64-v127 are compared. Easiest: do not touch them.
- Every store and every branch in your body cites its mnemonic in a comment, the way the lifted
  form does, so the rewrite is auditable line by line.

## The file shape

```cpp
// sub_82B29278  role: <one line>              lifted: skate3_recomp.67.cpp:27822 (11 lines)
// STATUS: pending | verified | divergent | uncalled | gate-1 (why) | gate-2 (why) | gate-3 | gate-4
// calls/session: boot N  play N  map N          thread: RwAudioCore Dac
// note: probe/ports/notes/sub_82B29278.md
namespace port_82B29278 {

constexpr uint32_t kSomethingOffset = 364;  // name it only if docs/rw_audio_structs.h names it

REX_FUNC(Native) {
  const uint32_t object = ctx.r3.u32;
  REX_STORE_U16(object + kSomethingOffset, ctx.r6.u16);  // sth r6,364(r11)
  ctx.r3.s64 = 0;                                        // li r3,0
}

// Every byte the call writes, from ENTRY state only. Return false if it cannot be known
// before the call (say why in the note: that is the gate-2 label).
bool Windows(PPCContext& ctx, uint8_t* base, skate3::audio::PortSpec& spec) {
  spec.write(ctx.r3.u32 + kSomethingOffset, 2);
  return true;
}

}  // namespace port_82B29278
SKATE3_PORT(82B29278, skate3::audio::kPortPending, skate3::audio::kReturnR3)
```

- `REX_LOAD_*`/`REX_STORE_*`, `REX_RAW_ADDR`, `sub_*` declarations and the SIMDe intrinsics are
  all available: the aggregator includes `generated/skate3_init.h` and `skate3_audio_port.h`.
- Keep helpers inside `namespace port_XXXXXXXX` so nothing collides in the shared TU. A helper
  that uses `REX_LOAD_*`/`REX_STORE_*` must take `uint8_t* base` as a parameter (the macros
  expand to code that names `base`); pass it through from Native/Windows.
- STATUS starts as `kPortPending`. Use `kPortGate1/2/3/4` when the function cannot be
  compared (see the gates below) -- the body is still written and still valuable.
- The result mask: `kReturnNone` for a void function; `kReturnR3` when the caller uses r3;
  `kReturnF1`; `Vr(n)`, `Gpr(n)`, `Fpr(n)` combined with `|` for register-only kernels
  (results in volatile vector registers). Compare everything the CALLER could read; comparing
  scratch the caller ignores produces false divergences, so read the call sites if unsure.
- Reads: `spec.read(addr, len)` for the memory the function reads but does not write (the
  object it takes, its command record). Not compared; recorded so the vector is replayable.

## Windows(): the only hard part

Enumerate the write set from entry registers and memory readable before the call. Loads are
fine (`REX_LOAD_U32(ctx.r3.u32 + 0x148)` to find a list head), bounded list walks are fine
(cap them; an unbounded walk is not enumerable). Include the writes of every callee you call.
Exclude the function's own frame and callees' own frames.

Return `false` when the addresses or lengths only exist DURING the call -- a length a callee
computes, a pointer loaded after a store that could alias it, an unbounded loop. Say why in the
note. Returning false is a correct answer; a window set that misses a byte is not.

Budget: 32 KB total, at most 32 spans. Over that, return false.

## The four gates (label, do not skip the rewrite)

1. **Callees replayable.** Anything that allocates, frees, releases, signals, submits, takes a
   lock or calls through a function pointer cannot be replayed on rewound memory. If the
   function reaches such a call on SOME paths only, Windows() may return false on those paths
   (predict them from entry state) and true on the rest. If on every path: `kPortGate1`.
2. **Write set enumerable** from entry state, within budget. Else `kPortGate2`.
3. **Deterministic.** `mftb` (`REX_QUERY_TIMEBASE`) or anything time-dependent: `kPortGate3`.
4. **Observable.** No stores and results only in registers the harness cannot see: name them
   in the result mask. If you cannot tell what the caller reads: `kPortGate4`, and say so.

## Before you finish

Run `python3 probe/ports/lint.py recomp/src/audio_ports/sub_XXXXXXXX.inc` and fix what it
reports. It checks the mistakes that otherwise cost a whole build cycle: a helper using
`REX_LOAD_*`/`REX_STORE_*` without a `uint8_t* base` parameter, a namespace or macro address
that does not match the file name, a missing header line, an unbounded `spec.write()` loop, a
direct `__imp__` call, and a port that declares neither a write nor a result register (which
would compare nothing at all). It does not compile the file, so it is fast and safe to run.

## The note (probe/ports/notes/sub_XXXXXXXX.md)

Five to fifteen lines: what the function does and for which structure; its arguments; every
store (address expression, size); the window rationale; the gate verdict and why; anything
you were unsure of. No narrative. This is what the next person reads when it diverges.

## What you get in the package

- The lifted body (`python3 tools/extract_lifted.py --one XXXXXXXX`).
- Its census entry (`probe/screen/out/census.json`): callees, imports, indirect calls,
  store census, per-store base-register provenance, transitive gate-1 verdict.
- `docs/rw_audio_structs.h` for the layouts already recovered. Use those names; do not invent
  names for offsets nothing documents -- a plain `+0x1A4` constant is honest.
- A verified example port to copy the shape from.
- Call counts and thread from the dynamic census, when available.

Do not touch any other file. Do not build. Do not run the game.
