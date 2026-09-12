# sub_82B1D7B0

Leaf, 19 lines, no stores. `r3` = `s32[r3+8] * s32[r3+4]`, capped at `u32[r3+0]` when the
product's low word exceeds it signed. Read set `{r3, 12}`; `kReturnR3`.

The exactness point: RexGlue lowers this `mullw` as a full 64-bit product
(`int64_t(s32) * int64_t(s32)`), so on the uncapped path r3 carries bits above 31 whenever the
product overflows, while the comparison sees only the low word. A 32-bit multiply would diverge
there. The cap is returned zero-extended, as loaded.

No direct call site; reached through a function pointer.
