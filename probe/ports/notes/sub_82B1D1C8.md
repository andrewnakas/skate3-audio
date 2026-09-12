# sub_82B1D1C8

Leaf, 30 lines, no stores, no callees, no timebase. Argument: r3 = an 8-byte operand block.
Reads `dividend` at +0 and `divisor` at +4. Returns in r3 the **signed 32-bit quotient**
`s32[+0] / s32[+4]`, zero-extended into the 64-bit register (`divw` writes a 32-bit result, so
r3's high word is always 0). When the divisor's low word is 0 the function returns early with
`li r3,0` and never reads +0.

Arithmetic sibling of three verified ports on the same 8-byte block: slot 23 `sub_82B1D1A8`
(+0 minus +4), slot 24 `sub_82B1D1B8` (product), slot 36 `sub_82B1D198` (sum). Nothing in
docs/rw_audio_structs.h names the block, so the offsets stay literal.

Two `tw` traps are reproduced, both calling `ppc_trap(ctx, base, 0)`, which in
generated/skate3_init.h only logs a warning and returns -- no state change either way:

- `twllei r11,0` (divide by zero) is **unreachable**: the `beq` above it already returned for
  divisor == 0. The lifted line's `r11.u32 < 0u` half is dead and is dropped, because clang
  rejects a tautological unsigned compare in src/ even though it is fine in generated/.
- `twlgei r7,-1` is the **divw overflow trap**, expressed obliquely:
  `r7 = r11 & ~(rotl32(r9,1) - 1)`, and since r11 is a zero-extended load r7 never exceeds 32
  bits, so `r7 == 0xFFFFFFFF` requires divisor == -1 and `rotl32(dividend,1) == 1`, i.e.
  dividend == INT32_MIN. Checked after the divide, as lifted.

The overflow case matters for exactness, not just for the trap: RexGlue's `divw` defines
INT32_MIN / -1 as **0**, while real hardware leaves 0x80000000. The harness compares against
the lifted form, so the port returns 0 there; it is also what keeps the C++ division out of
undefined behaviour. The lifted guard's `r11.s32 &&` half is already settled by the branch.

Stores: none. Own frame: none (no `stwu`, no `__savegprlr` spill). Callee-saved registers
untouched. r7-r11 and cr6 are volatile scratch, not compared, not reproduced.

Window: empty. Read set `{r3, 8}` -- the divisor word always, the dividend word only on the
nonzero path; recording both keeps the vector replayable either way. `Windows()` always
returns true.

Caller / gate 4: no direct call site in the lifted tree (the address appears only in
skate3_init.cpp, skate3_register.cpp and skate3_audio_census_all.cpp). It is **slot 25**
(0x82FD3664) of the opcode table at guest 0x82FD3600, confirmed by reading the table out of
`probe/harness/out/image/g_82E0.bin` at offset 0x1D3664. The interpreter `sub_82B1E290` calls
the slot through `bctrl` with r3 = the block and stores the returned r3's low word back into
the block, so r3 is consumed: `kReturnR3`. The harness compares all 64 bits, which is stricter
than the interpreter and safe because the high word is provably 0 on both paths.

Gates: 1 pass (leaf, no imports, no locks, no indirect calls); 2 pass (write set empty);
3 pass (no `mftb`); 4 satisfied by `kReturnR3`. STATUS: pending.
boot: 137,664 calls on RwAudioCore Dac.

Unsure: only what the block means. `a / b` over a two-word block with a zero-divisor guard is
consistent with an expression-evaluator opcode (the table's other slots are add, subtract,
multiply, sum-with-cap, saturating subtract), but no evidence names the fields, so no offset
names were invented. Whether the INT32_MIN / -1 path is ever reached in practice is unknown;
if a divergence ever appears here, that is the first thing to check.
