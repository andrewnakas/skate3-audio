# Decompilation status

## Pipeline

Ghidra 12.1.3 (Homebrew formula — there is **no** `ghidra` cask; `brew install ghidra`),
JDK 21. The image is imported as a raw binary at `0x82000000` with language
`PowerPC:BE:64:A2ALT-32addr`.

```sh
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
GH=/opt/homebrew/Cellar/ghidra/12.1.3/libexec/support/analyzeHeadless
$GH out/ghidra skate3 -import <image> \
    -processor PowerPC:BE:64:A2ALT-32addr \
    -loader BinaryLoader -loader-baseAddr 0x82000000 -noanalysis
$GH out/ghidra skate3 -process default_82000000_011B0000.bin -noanalysis \
    -scriptPath tools/ghidra_scripts \
    -postScript DecompileAudio out/audio_funcs.txt out/decomp
```

`-noanalysis` is deliberate: auto-analysis over an 18 MB image with 47,652 functions is
expensive and unnecessary here, because the exact entry points are already known from the
recomp's `generated/` output. `DecompileAudio.java` defines a function at every listed
address *first* — so calls between them render as named callees rather than raw pointers —
then decompiles each one.

## Result

**1,536 of 1,536 functions decompiled, 0 failures, 95,537 lines of C (7.1 MB)** in about a
minute. Output is one `sub_XXXXXXXX.c` per function under `out/decomp/`.

Quality was validated against ground truth before trusting the bulk run: `sub_82B28A00`'s
decompilation reproduces every struct offset the recomp had inferred from crash dumps
(`Player+8`, `System+0x30`, `System+0xCC`) and the publish-before-store ordering, matching
the PPC listing quoted in `skate3_audio_fixes.cpp`. See `command-queue.md` — it also
corrected that analysis on record length.

167 outputs are under 8 lines (thunks and trivial helpers).

## The VMX128 gap — 40 functions, and they are the ones that matter

43 outputs contain `halt_baddata` ("Bad instruction — truncating control flow"). The cause
is **VMX128**, Xenon's extended vector ISA, which Ghidra's PowerPC models do not decode.
Measured against the recomp's lifted output, which decodes it correctly:

- **40 of 1,536 audio functions (2.6%) contain VMX128**, 3,915 instructions in total.
- Most used: `lvx128` (916), `stvx128` (464), `vmulfp128` (362), `vor128` (332),
  `vperm128` (195), `vaddfp128` (192), `vsubfp128` (164).
- Heaviest: `sub_82B22898` (583), `sub_82B3A048` (557), `sub_82B02C30` and `sub_82B09288`
  (389 each).

These are the vectorised float DSP kernels — the mixing and filtering math. So the 2.6%
that fails to decompile is disproportionately the part the Rust port most needs to get
right, and a "1,496 of 1,536 succeeded" figure would be misleading.

`sub_82B22898` is `FrequencyShiftSsb`'s function and `sub_82B238A8` is `GainFader`'s, both
already named from the plug-in metadata — so the heaviest VMX128 users line up with known
DSP plug-ins, which is a useful cross-check.

Two ways forward, not mutually exclusive:

1. **Use the recomp's lifted C for these 40.** RexGlue decodes VMX128 correctly and emits
   one C++ statement per instruction with the mnemonic in a comment. For vector kernels
   being reimplemented as vector math anyway, that is a usable source — arguably better
   than decompiled C, which would hide the lane structure.
2. **Extend Ghidra's SLEIGH with VMX128.** The larger job, and the only route to genuine
   decompiled C for these. Worth it only if the lifted form proves too hard to read.

Option 1 first; revisit 2 if the DSP reimplementation stalls.

## Next

- Read `sub_82B28B78`, `0x82B28C18`, `0x82B28CC0` — the command consumers that define the
  queue's wire format.
- Pin the `0x8210A310` corrupting copy to one call site now that 95k lines of C are
  searchable.
- Cross-reference the 114 metadata-derived names into the decompiled output.

## Call-graph closure — and where the boundary actually is

The address window `0x82B00000`–`0x82B87000` is leaky (see `rw-audio-core.md`), so the
corpus was closed over the call graph instead of trusting the window.

`tools/resolve_callees.py` classifies every callee by reading the recomp's lifted sources,
where each `// bl 0x<addr>` comment is followed by the call it lowered to. That
distinguishes the three kinds of callee the decompiled C renders identically as
`func_0x…`:

| round 1 frontier | count |
|---|---|
| kernel imports (`__imp__…`) | 55 |
| compiler helpers (`__savegprlr_28`, …) | 47 |
| real guest functions | 158 |
| unresolved | 0 |

Decompiling those 158 brings the corpus to **1,694 functions**. Recomputing the frontier
then gives 130 guest functions — and **none of them are in the audio band**. They cluster
in `0x82F5xxxx` (30) and `0x82EExxxx` (17), which are the CRT and shared runtime
(`0x82EE5E80` is `memset`, `0x82F52xxx` is the `__savegprlr_*` family).

So the boundary is real, not arbitrary: **the audio subsystem is 1,694 functions**, and
every remaining callee is general-purpose runtime shared with the rest of the game. Chasing
full closure would decompile most of the 47,652-function binary for no benefit.

## The audio subsystem's kernel API surface

The 55 resolved imports are what the audio code actually asks the OS for. The XMA set
confirms the architecture — direct hardware context management, with no XAudio2 voice API
anywhere:

```
XMACreateContext          XMAInitializeContext      XMAEnableContext
XMADisableContext         XMASetInputBuffer0/1      XMASetInputBuffer0Valid/1Valid
XMAIsInputBuffer0Valid/1Valid                       XMASetInputBufferReadOffset
XMAGetOutputBufferReadOffset  XMAGetOutputBufferWriteOffset
XMASetOutputBufferReadOffset  XMASetOutputBufferValid  XMAIsOutputBufferValid
XAudioGetSpeakerConfig
```

Synchronisation is `RtlInitializeCriticalSection` /
`RtlInitializeCriticalSectionAndSpinCount` / `RtlEnterCriticalSection` /
`RtlLeaveCriticalSection`, plus `KfAcquireSpinLock` / `KfReleaseSpinLock` /
`KeAcquireSpinLockAtRaisedIrql` / `KeReleaseSpinLockFromRaisedIrql`.

`XAudioGetSpeakerConfig` is the **only** `XAudio*` import — consistent with the recomp's
kernel shim, which implements it as a constant and stubs the rest. The `Vd*` display
imports in the list come from non-audio functions that fall inside the address window,
which is itself further evidence the window is not the right boundary.

For the Rust port this is the list of host primitives that need equivalents: a recursive
mutex, a spinlock, and an XMA decoder driven by a paired input/output ring-buffer protocol.

## Symbol application, and a corpus-wide decompiler fix

### 420 names applied

`out/names.csv` collects every name recovered so far and `ApplyNames.java` pushes them into
the Ghidra database (126 renamed, 294 created for imports and helpers that were never
decompiled). Sources: the 114 plug-in names from the metadata, 294 kernel imports and
compiler helpers resolved from the lifted sources, and 12 hand-derived names from this
session's reading (the `PacketPlayer` event handlers, the codec lookups, the drain).

After re-decompiling, call sites read symbolically —
`__imp__RtlEnterCriticalSection(...)` rather than `func_0x82f9cb44(...)`.

### The `__savegprlr_*` problem — every function's parameters were wrong

Xenon prologues call register save/restore stubs (`__savegprlr_26` and friends) which use a
custom convention. Ghidra modelled them as ordinary functions, so a prologue decompiled as

```c
iVar2 = __savegprlr_26();     // then iVar2 used as the object base
```

and the real first argument in `r3` was **lost**. Every function using one had its
parameters mis-recovered, and the object base showed up as the "return value" of a stub
that returns nothing. This affected most of the corpus and would have quietly corrupted any
struct-offset work built on it.

`FixHelpers.java` sets the 84 save/restore stubs to `void`, strips their parameters, and
marks them inline. The drain went from

```c
void rwaudio_System_DrainCommandQueue(void)        // object base invented
```

to

```c
void rwaudio_System_DrainCommandQueue(int param_1) // param_1 + 0x54, + 0x60, ...
```

Corpus-wide: **1,304 functions now recover parameters**, against 95 still genuinely
parameterless.

**Tradeoff, recorded honestly:** re-decompiling after the change wrote 1,688 of 1,694 —
**6 functions that previously decompiled now fail**, so those 6 files hold their earlier
pre-fix output. Only `sub_82B43340` is detectable from its content (it still shows the
un-inlined pattern); the other five retain valid but pre-fix decompilations. 0.35% of the
corpus, worth revisiting if any of the six turn out to matter.

## What the drain actually does

`sub_82B48530` is named "the queue drain" in `skate3_audio_fixes.cpp`. Reading it, that is
approximately but not exactly right, and the difference matters for the race:

- It does **not** hold the System lock throughout. It takes the lock, calls
  `sub_82B48A50(System + 0x70, 0)`, and **releases it**; runs a fade/ramp pass unlocked;
  then re-acquires for `sub_82B482F8` and `sub_82B48440`.
- Locking is indirect: `System+0x54` and `+0x58` are lock/unlock function pointers, falling
  back to `RtlEnterCriticalSection`/`RtlLeaveCriticalSection` on `System+0x60` when null.
  This **confirms** `kSysLockFn` 84, `kSysUnlockFn` 88, `kSysCritSec` 96.
- `sub_82B48A50` is not a command-queue consumer at all — it walks a linked list of nodes
  from a 32-byte-stride bucket array at `System+0x10` and dispatches each node's function
  pointer with a float time delta. It is the **plug-in tick**, and it stores per-node
  elapsed time, so the engine profiles every plug-in every frame.
- `sub_82B482F8` and `sub_82B48440` walk two further lists at `System+0x1C` and `+0x20`.

So `System` owns several distinct lists, and the command ring (buffer `+0x30`, offset
`+0xCC`) is consumed somewhere not yet located — grepping for those two offsets is too
noisy to find it, since both are common offsets on unrelated objects.

`sub_82B1F7E8` is a timer read, called around every phase.

## Coverage is now complete — 1,694 of 1,694

The VMX128 gap is closed, not by extending Ghidra, but by taking the lifted form for the
functions Ghidra cannot read.

`tools/extract_lifted.py` pulls RexGlue's C++ for a list of addresses out of `generated/`,
one file per function, with the source translation unit and line recorded in a header
comment. RexGlue decodes VMX128 correctly and emits one statement per instruction with the
original mnemonic above it, so struct offsets stay visible:

```cpp
// lfs f0,268(r3)
temp.u32 = REX_LOAD_U32(ctx.r3.u32 + 268);
ctx.f0.f64 = double(temp.f32);
```

For vector DSP kernels this is arguably the better reference: it keeps the lane structure
explicit, which decompiled C would flatten into scalar temporaries.

| | count |
|---|---|
| corpus functions | 1,694 |
| usable Ghidra C | 1,642 |
| lifted C++ instead (`out/lifted/`) | 52 |
| **no usable form** | **0** |

### What the 52 are

**40 are VMX128** — the vector DSP kernels, led by `sub_82B22898` (`FrequencyShiftSsb`,
2,342 lines lifted) and `sub_82B3A048`.

**12 are not.** Re-measuring after the frontier expansion and the helper fix, `halt_baddata`
went from 43 to 52 — but that is not a regression from `FixHelpers`. The corpus itself grew
by 158 functions in the same period, and most of the extra failures are CRT routines pulled
in by the call-graph closure (`0x82EE5E80` is `memset`, alongside `0x82EDF460`,
`0x82EE25B0`, `0x82EE5BD0`) which are hand-written assembly. They are listed in
`out/undecodable_other.txt` and have lifted forms too.

The earlier "1,496 of 1,536 succeeded" framing is now moot: every function in the audio
subsystem has a readable form, with the reason for each choice recorded.

## Recovered structure layouts

`docs/rw_audio_structs.h` codifies the layouts established so far — `rw_system`,
`rw_player`, `rw_scheduler`, `rw_node`, `rw_instance`, `rw_packet`, `rw_command` — with
every offset cited to the function it was read from. Eleven fields are marked
`(confirmed)`: they independently reproduce values `skate3_audio_fixes.cpp` had inferred
from crash dumps, and they agree.

`docs/rw_audio_structs_check.c` asserts all 27 known offsets with `_Static_assert`:

```sh
clang -I docs -fsyntax-only docs/rw_audio_structs_check.c
```

This is not ceremony. The first version of the header compiled cleanly but placed
`cmd_write_off` at 0xC8 instead of 0xCC — the `rw_scheduler` sub-struct is 0x50 bytes and
ends at 0xC0, not the 0xC4 its pad name assumed, so everything after it was off by four.
A header that merely compiles proves nothing about offsets; the assertions are what make
it trustworthy, and they must be re-run whenever a field is added.

### The scheduler

`System + 0x70` is a scheduler the drain ticks twice a frame, buckets 0 and 1. Each bucket
is a linked list of nodes; each node points at a plug-in instance whose `process` function
is called with the frame delta. The instance's descriptor carries a flag at +0x0C deciding
whether to record per-tick elapsed time into the instance — so the engine's per-plug-in
profiling is switchable at runtime, per plug-in.

A node that removes itself during its own callback sets a flag at `scheduler + 0x4C`, which
the loop checks after every dispatch — so plug-ins are allowed to detach themselves mid-tick,
and any reimplementation has to preserve that.
