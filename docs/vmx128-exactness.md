# VMX128 bit-exactness: measured, and the translation cookbook

**Phase 0b. Result: GO.** A Rust translation of RexGlue's VMX128 lowering reproduces it
bit-for-bit — 45 of 45 operations, 56,880 lane comparisons, zero divergence — subject to
one rule the plan did not anticipate, written up as rule 4 below.

`CLAUDE.md` calls VMX128 exactness "the single biggest risk in any effort estimate" and
says to measure before promising. This is that measurement. Reproduce with
`probe/vmx128/run.sh`; it needs no Ghidra, no game build, no game data and no play session.

## Why this was cheaper than it read

The risk was framed as "can scalar reproduction be bit-identical to Xenon vector
hardware." That is not the question the port actually faces, because **RexGlue already
solved the lowering** and the result is on disk in `generated/`. The real question is the
much narrower "can Rust reproduce *RexGlue's* lowering," and the whole VMX128 surface
turns out to reduce to three categories:

| category | count | portability |
|---|---|---|
| direct SSE/SSE4.1/FMA intrinsics | most | `core::arch::x86_64` has each one 1:1 |
| RexGlue helpers in `rex/ppc/intrinsics.h` | 8 | pure integer/scalar code, ports literally |
| scalar libm per lane (`exp2f`, `log2f`) | 2 | measured identical; see rule 5 |

Nothing in the audio corpus needs a hardware estimate instruction whose precision is
unspecified. `vrsqrtefp` in particular is **not** `_mm_rsqrt_ps`: RexGlue implements it as
`ppc_vrsqrtefp_bits`, an integer table lookup with a 32-entry constant table, so it ports
as data plus arithmetic and cannot drift.

## The instruction surface, measured

Scanned across all 47,652 lifted functions in `generated/`, restricted to the audio
address range `[0x82AE0000, 0x82B60000)`:

- **67 functions** contain vector instructions
- **10,295 vector instructions** total
- **76 distinct mnemonics**

The probe covers 45 operations spanning every distinct lowering family in that set — all
float arithmetic, all conversions, all estimates, the permute/select/pack/shift families
and the BE↔LE lane mask.

> Reconciling with `docs/decompilation-status.md`, which reports 40 functions and 3,915
> instructions: that count is against the 1,694-function audio corpus and appears to count
> strictly `*128`-suffixed mnemonics. The counts agree where they overlap — `sub_82B22898`
> measures 583 in both. The figures here are a superset (a wider address range, and plain
> VMX alongside VMX128), not a contradiction.

## The cookbook

### 1. `vmaddfp*` is a genuine fused multiply-add

`vmaddfp`, `vmaddfp128` and `vmaddcfp128` lower to `simde_mm_fmadd_ps`; `vnmsubfp*` to
`simde_mm_fnmadd_ps`. Both are single-rounding. Translate to `_mm_fmadd_ps` /
`_mm_fnmadd_ps`, never to `a * b + c` — LLVM will not contract a separate multiply and add
without fast-math, so the failure mode is a human writing the algebraic form, not the
compiler. A `vmulfp128` followed by a separate `vaddfp128` must stay two operations.

Verified: `vmaddfp` and `vnmsubfp` are bit-identical over the full adversarial set.

### 2. Flush-to-zero is toggled per instruction class, not per function

`ctx.fpscr.{enable,disable}FlushModeUnconditional()` is emitted before individual
instructions — 970 `disable` and 136 `enable` in `skate3_recomp.67.cpp` alone. VMX is
always flush-to-zero; the scalar FPU follows the guest's FPSCR. A single global FTZ choice
diverges on any kernel that mixes vector and scalar float work, and several do.

FTZ is MXCSR `FLUSH_ZERO | DENORMALS_ZERO` (`0x8000 | 0x0040`). In Rust, `_mm_setcsr` is
deprecated; use `stmxcsr`/`ldmxcsr` via `asm!` as `probe/vmx128/rust/src/main.rs` does.

Verified: every operation was run under both MXCSR states, and both match.

### 3. The BE↔LE lane mask ports as literal data

Every vector load and store passes through `simde_mm_shuffle_epi8(..., VectorMaskL)`.
`VectorMaskL` row 0 is the plain byte reversal `0x0F…0x00` used by `lvx128`/`stvx128`;
rows 1–7 carry `0xFF` fill bytes for the misaligned `lvlx`/`lvrx`/`stvlx`/`stvrx` forms.
Copy the table and use `_mm_shuffle_epi8` with the identical mask.

Verified as `lvx128_swap` and `lvlx128_swap5`.

### 4. Commutative float ops are not NaN-commutative — pin the operand order

**This is the one rule that is not mechanical, and the only source of divergence found.**

`_mm_add_ps` and `_mm_mul_ps` are commutative in value but not in NaN payload: the result
carries the NaN of whichever operand the compiler placed in `src1`. **GCC's choice is an
artifact of register allocation and is not stable**, so the same source produces different
NaN behaviour in different contexts:

| context | GCC emits | picks |
|---|---|---|
| inlined, straight-line | `vaddps` with `src1 = a` | `a` |
| noinline, args in `xmm0`/`xmm1` (RexGlue's actual shape) | `vaddps %xmm0,%xmm1,%xmm0` | `b` |

Adding one unused third argument to the function signature was enough to flip it. LLVM
consistently chose `a` in every context tested, so C++ and Rust disagree whenever a NaN
reaches `vaddfp`/`vmulfp`.

Three consequences, in order of importance:

1. **`a`-first is the architecturally correct answer.** AltiVec returns the first NaN
   operand in the order `vA`, `vB`. Rust matched real Xenon semantics here; the
   GCC-compiled C++ did not.
2. **The C++ recomp is not bit-stable against itself** on NaN inputs. A refactor that
   changes inlining can change NaN propagation without touching a line of arithmetic.
   This is a latent RexGlue property, not something the Rust port introduces.
3. **A register barrier is not enough.** `asm("" : "+x"(a))` pins the operand to a
   register and GCC still commutes the instruction. Only writing the instruction out —
   `asm("vaddps %2,%1,%0" : "=x"(r) : "x"(a), "x"(b))` — fixes `src1`.

With operand order pinned this way, the probe reports **ALL OPS BIT-IDENTICAL**. Without
it, 43 of 45, the two exceptions being `vaddfp128` and `vmulfp128` and only on NaN lanes.

**Rule:** for `vaddfp*`, `vmulfp*`, `vmaxfp*` and `vminfp*`, treat `src1 = a` as part of
the semantics. How much this matters in practice depends on whether NaN ever reaches these
kernels, which is an empirical question the shadow harness should answer — see "What this
does not settle".

### 5. `vexptefp128` and `vlogefp128` go through libm

RexGlue lowers these to scalar `exp2f`/`log2f` per lane, not to a vector approximation.
Measured bit-identical between glibc's `exp2f`/`log2f` and Rust's `f32::exp2`/`f32::log2`
across the adversarial set, because on this platform Rust's lower to the same glibc
symbols.

**That is a platform coincidence, not a guarantee.** These two are the only operations in
the surface whose exactness depends on something outside the translation. Keep them in the
per-function bit-compare permanently rather than treating them as settled, and re-check
them on any toolchain or libc change.

Note separately that real Xenon `vexptefp`/`vlogefp`/`vrefp` are 12-bit-accurate *estimate*
instructions, whereas RexGlue uses correctly-rounded `exp2f`/`log2f` and a true
`_mm_div_ps` reciprocal. So the recomp already differs from real hardware at these 51
sites. That is consistent with this project's definition of exact — the recomp's own mixer
output is the oracle — but it means "the recomp's audio is already exact" is a statement
about the reference, not about Xenon.

### 6. Build requirements

`rex/ppc/context.h` compiles standalone in 0.6 s against `rex/types.h`, `rex/platform/fpscr.h`
and vendored SIMDe. It needs **`-std=c++23`** (`rex::byte_swap` uses `std::byteswap`);
C++20 fails. `sizeof(PPCContext)` is 2688 bytes. Build both sides with `-march=native` /
`-C target-cpu=native` so FMA and SSE4.1 are available without runtime dispatch.

## What this does not settle

- **Whole-kernel composition.** The probe verifies operations individually. It does not
  run a whole lifted kernel end to end, because every one of the five heaviest calls
  between three and nine other guest functions, so a standalone link needs stubs. Worth
  doing once against a real kernel in Phase 3, but the per-operation result is what
  determined go/no-go.
- **Whether NaN reaches the DSP at all.** Rule 4 only bites on NaN inputs. If NaN never
  enters these kernels during play, it is a non-issue; if it does, it is a real divergence
  source in both directions. The shadow harness can answer this cheaply once Phase 1 is
  up — add a NaN counter at the kernel boundary.
- **ARM64.** Deliberately out of scope per `PLAN.md` non-goals. Note rule 4 would need
  re-deriving there: NEON `FADD` has its own NaN ordering.

## Corrections to the planning documents

- `PLAN.md` §2 phase 0b says to extract "one FMA-heavy, one not, ideally `sub_82B22898`."
  **`sub_82B22898` contains zero FMA sites.** It is the largest kernel (583 vector
  instructions) but is FMA-free; the FMA-heavy kernels are `sub_82B02C30` and
  `sub_82B09288`, 36 `simde_mm_fmadd_ps` sites each.
- `docs/environment-linux.md` reports 999 `disable` / 136 `enable` FTZ sites in
  `skate3_recomp.67.cpp`; measured now as **970 / 136**. The 136 matches exactly; the
  disable count does not. Immaterial to the conclusion, recorded for honesty.
- `PLAN.md` §8 risk 1 ("VMX128 Rust bit-exactness") is **retired** for go/no-go. It
  survives only as the per-kernel bit-compare in Phase 4, plus the two libm operations in
  rule 5, which should stay checked indefinitely.

## Files

| file | what |
|---|---|
| `probe/vmx128/run.sh` | builds both sides, runs, compares. One command. |
| `probe/vmx128/gen_vectors.py` | adversarial vectors — denormals, NaN payloads, ±0, ±inf, rounding boundaries, conversion edges, an `rsqrt` table sweep, 512 xorshift patterns. Written once to a file both sides read, so the two cannot disagree about inputs. |
| `probe/vmx128/cpp/runner.cpp` | the reference. Every body is RexGlue's lowering verbatim. `-DPIN_COMMUTATIVE_OPERAND_ORDER` applies rule 4. |
| `probe/vmx128/rust/src/main.rs` | the candidate: hand translation to `core::arch::x86_64`. |
| `probe/vmx128/compare.py` | per-op, per-FTZ-state diff with first differing lanes. |
