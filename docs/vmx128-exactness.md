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

### 1. `vmaddfp*` rounds twice in the recomp — it is **not** a fused multiply-add

*Corrected 2026-09-13.* Until then this rule said the opposite, which is wrong for the game.

`vmaddfp`, `vmaddfp128` and `vmaddcfp128` lower to `simde_mm_fmadd_ps`; `vnmsubfp*` to
`simde_mm_fnmadd_ps`. What those become depends on the compiler flags. The recomp is built with
`-O3 -march=x86-64 -msse4.1 -mtune=generic` and no `-mfma`, so `__FMA__` is undefined and SIMDe
takes its portable fallback: `(a * b) + c` and `-(a * b) + c`, a rounded product and then a
rounded add. clang-20 emits exactly `mulps` then `addps`, and `mulps` then `subps`: it rewrites
`-(p) + c` as `c - p`. The recomp's lifted sine kernel `sub_824531C8` is 25 `mulps`, 11 `addps`,
1 `subps` and no FMA instruction.

Translate to `_mm_add_ps(_mm_mul_ps(a, b), c)` and `_mm_sub_ps(c, _mm_mul_ps(a, b))`. A
subtraction is not commutative, so `vnmsubfp`'s NaN winner is fixed: `c`, then the product with its
sign *not* flipped. The scalar `fmadds` family is different. It lowers to `std::fma`, which is
correctly rounded with or without the instruction, so it stays single-rounding.

**How this was missed.** The probe built its reference with `-march=native`, which defines
`__FMA__`. So the reference itself was fused, and a fused Rust layer matched it 45 of 45. The
error surfaced in the recorded-vector replay: 4 of 2,000 real `sub_824531C8` calls disagreed.
Emulating two roundings matched all 16 distinct inputs, where the fused form matched 12. `run.sh`
now builds every reference with the recomp's flags. Against those builds the Rust layer is 45 of 45
on `clang20_pinned`, `gcc_pinned` and `clang20_plain`.

**Only one kernel's real data could tell the two apart.** Every other recorded vector replays
clean under both layers (48,399 of 48,403 fused, 48,403 unfused, the 4 all in the sine kernel).
The unit tests with constructed inputs pin `vmx`, `dsp::gain_ramp`, `dsp::scale`, `dsp::sine` and
`crossfade`, which failed when the layer changed. `stage` and `dsp::scale_add` have no test that
distinguishes the two.

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

**The one rule that is not mechanical, and the only source of divergence found.** It is
confined to lanes where two operands are NaN.

With two NaN operands, x86 returns the payload of one particular operand slot. Measured on
this CPU: for `vaddps`/`vmulps` the first source wins; for `vfmadd*`/`vfnmadd*` the first
*factor* of the encoded form wins (op2 in the 213 form, op1 in the 132 form). Which program
variable lands in that slot is a register-allocation decision, so for the same source
expression it changes with calling context — **in both compilers**, including clang-20,
which is what the recomp is built with (`CMAKE_CXX_COMPILER` in the jammy build cache):

| same expression, noinline function with signature | GCC 15.2 | clang 20 |
|---|---|---|
| `add_ps(a,b)` in `f(a,b,c)` | a | a |
| `add_ps(a,b)` in `f(a,b)` | a | a |
| `add_ps(a,b)` in `f(b,a)` | a | **b** |
| `fmadd_ps(a,b,c)` in `f(a,b,c)` | a | **b** |
| `fmadd_ps(a,b,c)` in `f(c,a,b)` | a | **b** |
| `fmadd_ps(a,b,c)` in `f(b,a,c)` | **b** | a |
| `fmadd_ps(a,b,c)`, operands loaded from memory | a | a |

In the probe's op table the two compilers fail on *different* pairs: GCC diverges from Rust
on `vaddfp128`/`vmulfp128`, clang-20 on `vmaddfp`/`vnmsubfp`. That was measured under `-march=native`. Under the recomp's own
flags, clang-20 unpinned matches Rust on all 45 and GCC unpinned diverges on `vmaddfp`/`vnmsubfp`
in two lanes of 632. The FMA rows of the table above describe instructions the recomp never emits.
Rust returned `a` in every
op, but that too is only what its own calling context produced.
The op table passes `__m128i`
arguments through a function pointer, and that alone is enough to flip GCC's add to `b`
relative to the direct `__m128` calls in the table above.

Consequences, in order of importance:

1. **The recomp is not NaN-stable against itself.** Which operand's NaN a lifted kernel
   propagates is chosen per site by clang's optimizer, not by the PPC source. A change to
   inlining or register pressure can change it without touching a line of arithmetic.
2. **So no translation can match the recomp from source alone.** If NaN reaches these
   kernels, matching the recomp at a given site means reading the winning slot out of the
   recomp binary's disassembly. If NaN never reaches them, none of this matters. That is an
   empirical question — see "What this does not settle".
3. **Xenon's own NaN precedence is not established.** An earlier version of this document
   asserted that AltiVec returns the first NaN operand. That was never sourced and is
   withdrawn. This project's definition of exact does not depend on it: the oracle is the
   recomp's mixer output, not Xenon.
4. **Pinning works, and has to write the instruction out.** A `"+x"` register barrier pins
   an operand to a register and the compiler still commutes the instruction.
   `-DPIN_COMMUTATIVE_OPERAND_ORDER` routes the four ops through naked functions whose
   encoding puts `a` in the winning slot. With it, **GCC and clang-20 are both 45/45**
   against Rust. `vmaxps`/`vminps` need no pinning: SSE defines them to return the second
   operand on NaN, so compilers must already preserve their order.

**Rule:** for `vaddfp*`, `vmulfp*`, `vmaddfp*` and `vnmsubfp*`, the operand slot is part of
the semantics. Native C++ and Rust should both pin it explicitly, and agree on one
convention, rather than inherit whatever each optimizer picks.

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
C++20 fails. `sizeof(PPCContext)` is 2688 bytes. The recomp itself is built with clang-20,
installed here only as `clang++-20` — there is no unversioned `clang++`, so check that name
before concluding clang is absent. Build the reference with the recomp's own
flags, `-O3 -march=x86-64 -msse4.1 -mtune=generic`, and **never `-march=native`**: that defines
`__FMA__` and silently changes what rule 1 measures. The Rust side may use `-C target-cpu=native`,
because it writes each intrinsic out and LLVM does not contract without fast-math.

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
- **ARM64.** Deliberately out of scope per `PLAN.md` non-goals. Rule 4 would need
  re-measuring there.

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
| `probe/vmx128/run.sh` | builds the reference under GCC and clang-20, plain and pinned, with the recomp's own code-generation flags, plus the Rust candidate; runs and compares all four. One command. |
| `probe/vmx128/gen_vectors.py` | adversarial vectors — denormals, NaN payloads, ±0, ±inf, rounding boundaries, conversion edges, an `rsqrt` table sweep, 512 xorshift patterns. Written once to a file both sides read, so the two cannot disagree about inputs. |
| `probe/vmx128/cpp/runner.cpp` | the reference. Every body is RexGlue's lowering verbatim. `-DPIN_COMMUTATIVE_OPERAND_ORDER` applies rule 4. |
| `probe/vmx128/rust/src/main.rs` | the candidate: hand translation to `core::arch::x86_64`. |
| `probe/vmx128/compare.py` | per-op, per-FTZ-state diff with first differing lanes. |
