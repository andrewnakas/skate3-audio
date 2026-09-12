# sub_82B3BED8

Leaf float-array scale: `dst[i] = src[i] * scale` for `i` in `[0, count)`. 280 lifted lines,
25 vector instructions, ~1.07M calls per boot session on `RwAudioCore Dac`. No callees, no
imports, no indirect calls, no timebase, no locks -- gate 1 passes trivially.

**STATUS: verified.** Session `s19` (probe/harness/out/s19.log, 2026-09-12 03:19-03:21):
`runs=1057635 diverged: registers=0 memory=0 skipped=0 overflow=0`. `skipped=0` is the part worth
reading twice -- `Windows()` answered on every one of the million calls rather than declining, and
`overflow=0` means the declared window stayed inside the budget every time.

Arguments: `r3` destination floats, `r4` source floats, `r6` the float count, `f1` the scale.
Nothing in `docs/rw_audio_structs.h` names either buffer, so the port declares no offset
constants; the only structure is "an array of floats".

Two paths, chosen on entry state alone:

- **vector**, taken when `((r3|r4) & 0x7F) == 0` and `(r6 & 0x3F) == 0` -- both buffers 128-byte
  aligned and the count a multiple of 64. 32 floats per iteration: eight `lvx128`, eight
  `vmulfp128`, a `dcbzl` on the destination line, eight `stvx128` in the lifted order
  (+16, +32, +48, +64, **+0**, +80, +96, +112). The loop exits on the *source* cursor reaching
  `r4 + count*4`, not on a counter.
- **scalar** (`loc_82B3BFD4`), any alignment and any count: `count/4` groups of four `fmuls`
  plus a one-float `lfsu`/`stfsu` tail.

## What the game actually passes

From the census's first-four dumps across sessions: `r6 = 0x100` (256 floats, a 1 KB window)
every time, `r3`/`r4` always 128-byte aligned, so **the vector path is the one that runs**. `f1`
alternates between `1.0` and `0.0` -- a zero scale turns the call into a buffer clear. Two call
sites, `lr = 0x82B29B44` and `0x82B42768`.

## Stores

| where | address | size |
|---|---|---|
| `dcbzl r0,r11` | `(d & ~127)`, d = dst + 128k | 128 (fully overwritten by the eight stores that follow) |
| `stvx128` x8 | `d + {0,16,32,48,64,80,96,112}` | 16 each |
| `stfs` x4 | `d + {0,4,8,12}`, d = dst + 16k | 4 each |
| `stfsu` | `dp + 4`, walking to `dst_end` | 4 each |

`std r30,-16(r1)` / `std r31,-8(r1)` and the four `stfs f1,-{32,28,24,20}(r1)` are the function's
own frame (red zone) and are neither reproduced nor windowed, per the brief. The function restores
r30/r31 before every return, so no preserved register changes. Every clobbered vector register is
v55-v63, all volatile -- nothing in `v14-v31`/`v64-v127`, so the result mask is `kReturnNone` and
the memory window is the whole comparison.

## Window

`[r3, r3 + count*4)` on both paths, computed the way the original computes its end pointer
(`srawi` then `rlwinm`, not by eye). Reads: `[r4, r4 + count*4)`.

`Windows()` returns **false** on one predictable class: the vector path with a span that is zero
or not a multiple of 128 -- `count == 0`, or a negative count, or `count*4` overflowing 32 bits.
The lifted loop compares `r10 != r5` with a 128-byte stride, so none of those terminate; the
original **hangs**, and the native body reproduces the hang rather than guarding it. Also false if
`dst + len` would wrap the address space. The scalar path handles a zero or negative count by
returning immediately (`cmplw r11,r9 ; bge`), which the port declares as a zero-length write set,
i.e. a real comparison of "writes nothing". None of these fired in s19 (`skipped=0`).

## Limits of the green

- **The scalar path is unexercised.** Every logged entry point is 128-byte aligned with
  `count = 256`, so the 1.06M clean comparisons are almost certainly all vector path. The scalar
  path (`fmuls` groups plus the `lfsu`/`stfsu` tail) is verified only by a bounds/addressing
  cross-check: a Python model of the lifted register machine against a model of this port over 111
  cases -- six alignment combinations, 18 counts including 1/3/7/17/63/65/127, and three
  overlapping src/dst layouts -- agreeing on both the written bytes and the written address set.
  That checks addresses, loop counts and store order, not float rounding.
- The scale broadcast is `simde_mm_set1_ps(float(f1))` rather than four `stfs` to `-32(r1)`
  followed by `lvx128 v63,r0,r30`. Those agree only if the guest r1 is 16-byte aligned, because
  `lvx128` masks the low four address bits. Measured on the real entries: `r1 = 0x707BF960`, low
  four bits clear -- so the assumption is observed, not just argued from the ABI.
- If a caller ever placed the destination buffer inside this callee's own red zone, the original's
  r30/r31 spill would land inside the declared window and the native body (which does not spill)
  would differ. No such caller is plausible; recorded because it would present as a memory diff
  with no arithmetic explanation.
- `vmulfp128` keeps the scale as the **first** operand, as lifted, per `vmx128-exactness.md`
  rule 4: with two NaN operands the winning slot is part of the semantics.
