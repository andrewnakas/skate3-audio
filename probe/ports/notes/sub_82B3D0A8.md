# sub_82B3D0A8

Leaf crossfade mixer, 662 lifted lines, 56 vector instructions, **56,932 calls per boot session**
on `RwAudioCore Dac` (tier C). No callees, no imports, no indirect calls, no timebase, no locks --
gate 1 passes trivially.

**STATUS: verified.** Sessions `s22` and `s23` (`probe/harness/out/s22.log`, `s23.log`,
2026-09-12 03:48 and after): `runs=46166` and `runs=43854`, each
`diverged: registers=0 memory=0 skipped=0 overflow=0`. `skipped=0` means `Windows()` answered on
every call; `overflow=0` means the window stayed in budget. Read "Limits of the green" below
before quoting that: only one of the three paths ran.

## What it does

Six float arrays and two scalar gains. Per element `i`:

    F[i] = D[i]*C[i] + (1 - D[i])*B[i]
    E[i] = A[i] + fma((1 - D[i])*B[i], f1, (D[i]*C[i])*f2)

so `B` and `C` are two sources, `D` a per-sample crossfade coefficient, `F` the plain blend and
`E` the gain-weighted blend accumulated onto `A`. Nothing in `docs/rw_audio_structs.h` names any
of these buffers, so there are no offset constants.

Arguments: `r3` count, `r6` A, `r7` B, `r8` C, `r9` D, `r10` E, `84(r1)` F, `f1` and `f2` the two
gains. **`r4` and `r5` are never read**: the PowerPC ABI gives each float argument an FPR *and* a
GPR parameter slot, and those are `f1`'s and `f2`'s. That also fixes the stack slot -- eight-byte
slots from `20(r1)` put the ninth parameter at `84(r1)`, which is exactly what `lwz r30,84(r1)`
reads. `stw r3,20(r1)` spills the count into its own home slot; own frame, not reproduced.

## Two paths, three rounding shapes

- **vector**, taken when `(r7 & 0xF) == 0 && (r8 & 0xF) == 0`, for `floor(count/16)*16` elements,
  16 floats (four vectors) per pass. `F` is computed as **three separate operations** --
  `mul`, `mul`, `vaddfp` -- while both scalar paths **fuse** the same expression into `fmadds`.
  The two paths therefore round `F` differently. That is the original's, kept as found.
- **scalar, four-wide** (`loc_82B3D330`), for whole groups of four from where the vector path
  stopped. The four unrolled lanes do **not** associate the weighting identically:
  lanes `j` and `j+1` compute `(C*D)*f2`, lane `j+2` computes `(D*f2)*C`, lane `j+3` computes
  `(D*C)*f2`. Three different roundings of one algebraic expression, in one loop body. Each site
  is written the way it is lifted; factoring them into a shared helper would be a silent bug.
- **scalar, one at a time** (`loc_82B3D4A0`) for the remainder, using `(D*C)*f2`.

The `1.0` differs by path too: the vector path builds it from `vspltisw128 v63,0` plus
`vupkd3d128 v62,v63,0` (every source byte zero, so every lane is `0x3F800000`), while the scalar
paths **load** it with `lfs f0,-22460(r11)` after `lis r11,-32206`, i.e. from `0x8231A844`. The
port loads that word rather than assuming 1.0f -- the image was not read to confirm the value, and
it does not need to be.

## Stores

| where | address | size |
|---|---|---|
| `stvx128` x4 | `(E + 64k + {0,16,32,48}) & ~0xF` | 16 each |
| `stvx128` x4 | `(F + 64k + {0,16,32,48}) & ~0xF` | 16 each |
| `stfs` + `stfsx` x3 | `E + 4j + {0,4,8,12}`, j = done + 4k | 4 each |
| `stfsx` x4 | `F + 4j + {0,4,8,12}` | 4 each |
| `stfsx` | `E + 4m`, m walking to count | 4 |
| `stfsx` | `F + 4m` | 4 |

Everything else the census lists is the function's own frame: `20(r1)` (the count's home slot) and
`-164(r1)` through `-224(r1)` (the gain splat scratch and three 8-byte spills). There is no
`stwu`; `__savegprlr_14` puts r14-r31 in the red zone at `-152(r1)` upward, clear of the `-164`
scratch, and `__restgprlr_14` restores them on the single exit, so no preserved register changes.
Every clobbered vector register is v0-v13 and v32-v63, all volatile, so the result mask is
`kReturnNone` and the memory window is the whole comparison.

## Window

Two writes plus four reads per path, at most 13 spans, `4*count` bytes per output buffer -- within
budget up to `count = 4096`, above which the hook's oversize check fires.

The vector path's addressing is the one real subtlety. The entry test checks **only B and C** for
16-byte alignment; `A`, `D`, `E` and `F` are not checked, and every `lvx128`/`stvx128` masks the
low four address bits. So if `E` or `F` is misaligned the vector path reads and writes the buffer
**rounded down** to a 16-byte boundary, and the window has to start at `base & ~0xF`, not at
`base`. Since each of the four displacements is a multiple of 16, the masked span is exactly
`[base & ~0xF, +64*passes)`. The same masking is declared on the `A` and `D` reads.

`Windows()` returns **true** on every path. There is no non-terminating case here (unlike
`sub_82B3BED8`/`sub_82B44B20`): both loops are `mtctr`-counted, and a zero or negative count
falls out through `cmpw r27,r3 ; bge` writing nothing. It returns false only on the two
address-space-wrap guards, which cannot fire for a real buffer.

## What the game actually passes

From the census's first-four entry dumps in `s22`, one call site (`lr = 0x82B3D564`):

    r3 = 0x80 (128 elements)   r6 = A = 0x4B389B80 / 0x4B399B80   r7 = B = 0x4B3FF4D8
    r8 = C = 0x4B3FF4EC        r9 = D = 0x707BF8F0                r10 = E = 0x4B3FF900
    f1 = 0.0                   r1 = 0x707BF820

**B and C are 16-byte misaligned** (`0x...4D8`, `0x...4EC`), so the entry test fails and **the
vector path never runs**. `D` is not even a heap buffer: at `r1 + 0xD0` it is a stack temporary in
the caller's frame. With `count = 128`, a multiple of four, the four-wide scalar loop runs 32 times
and the one-at-a-time remainder never runs either.

So the 90,020 clean comparisons cover exactly one of the three paths -- but it is the one where all
three of the odd `f2` associations live, which is the part most likely to be got wrong.

## Limits of the green

- **The vector path is unexercised**, including its non-fused `F` computation and the masked
  addressing of the unchecked `A`, `D`, `E` and `F` pointers. If a caller ever aligns B and C, that
  path runs for the first time with no evidence behind it.
- **The one-float remainder loop is unexercised** (every observed count is a multiple of four).
- The gain broadcasts are `simde_mm_set1_ps(float(fN))` rather than four `stfs` to the red zone
  followed by `lvx128`. Those agree only if the guest `r1` is 16-byte aligned, because `lvx128`
  masks the low four address bits. Measured on the real entries: `r1 = 0x707BF820`, low four bits
  clear -- observed, not just argued from the ABI. (This only matters on the vector path, which
  does not run here.)
- The scalar-path element-address algebra was derived by reducing every lifted base-difference pair
  (`r23 = E-B`, `r28 = A-E`, ...) against the four cursors `r11 = &B[j+1]`, `r5 = &D[j+2]`,
  `r4 = &C[j+3]`, `r31 = &E[j]`; all 24 effective addresses reduce to a block base plus 0/4/8/12 in
  32-bit wrapping arithmetic. That reduction was the thing most likely to be wrong, and the 90k
  clean memory comparisons are what check it.

## Uncertainties

- If a caller ever placed `E` or `F` inside this callee's own red zone, the `__savegprlr_14` spill
  and the gain scratch would land inside the declared window and the native body (which spills
  nothing) would differ. Not plausible; recorded because it would present as a memory diff with no
  arithmetic explanation.
- The FTZ disable that the first `stfs f2,-192(r1)` emits sits *before* the `ble` that skips the
  vector loop, so the port issues it (and converts both gains) even when the loop does not run.
  That matches the lifted order.
