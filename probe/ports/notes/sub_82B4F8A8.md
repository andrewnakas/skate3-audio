# sub_82B4F8A8

Leaf, 17 lines. Arguments: r3 = an element count, r4 = out pointer for an alignment word.
Writes `16` to `u32[r4+0]` and returns `28 * ((r3 + 1) / 2) + 88` in r3 -- a size query, 88 bytes
of header plus 28 bytes per pair of elements, rounding the count up.

`rlwinm r10,r11,31,1,31` is a 32-bit rotate-left-31 masked to bits 1..31, which is an unsigned
shift right by one. Only the low 32 bits of r3 participate, so a caller leaving junk in the upper
half changes nothing. The product is on a zero-extended value below 2^31, so it cannot wrap.

Write set `{r4, 4}`, from entry state. `kReturnR3`. Gates 1-4 clean.
