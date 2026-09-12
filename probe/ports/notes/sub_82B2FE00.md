# sub_82B2FE00

Leaf, 113 lines, 4 calls in the boot profile. r3 = a rate field, r4 = a six-word output block.
Clamps `f32[r3]` into [lower, upper], reloads it, scales it twice, clamps the result at a
ceiling, then writes the span at `r4+20`, the base at `r4+0` and four equally spaced points at
`r4+4..r4+16`. On the ceiling path the rate field is overwritten with a pool constant and the
ramp starts from a different base, so `f0` at the tail differs between the two paths.

Write set `{r3, 4}` and `{r4, 24}`, both from entry state. `kReturnR3` (r3 = 1). Gates 1-4 clean.

**It diverged on its first shadow run, and the cause is worth recording.** I decoded
`lfs f13,18868(r9)` as offset 0x4BB4 instead of 0x49B4, so the second scale factor came from the
wrong address: `diverges in memory at 707BFB20+1 (lifted 34, native A6)`. Every other constant
in the function checked out; this one digit changed the product, which changed the ceiling
comparison and every stored point. Six constants are loaded here by `lis`/`addi` pairs, and
converting those offsets by hand is the error-prone step -- compute them, do not read them.

The rate field and the output block both sit on the guest stack in the observed call, which is
why the divergence address is in the 0x70030000..0x707BFB20 band.
