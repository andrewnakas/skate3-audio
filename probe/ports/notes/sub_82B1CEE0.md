# sub_82B1CEE0

Leaf, 15 lines, no stores. `r3` = the smaller of `s32[r3+0]` and `s32[r3+4]`, compared signed,
returned zero-extended as loaded (not sign-extended). Ties return the second field, since the
branch is `bgelr`. Read set `{r3, 8}`; result in r3 only, so `kReturnR3` satisfies gate 4.

Sibling of the verified `sub_82B1D198` (sum), `sub_82B1D1A8` (difference), `sub_82B1D1B8`
(product) and `sub_82B1CF38` (signed max) over the same two-field object. No direct call site:
reached through a function pointer, so r3 rests on the calling convention.
