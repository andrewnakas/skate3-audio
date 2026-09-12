# sub_82B46EA0

Leaf, 150 lines, five figures of calls per boot session (the `.inc` header carries the measured
count, and the current STATUS verdict with it), `RwAudioCore Dac`. r3 = a byte cursor into a
stream, r4 = a one-word output. Returns the number of bytes consumed (1..5) in r3. This is the
**signed** sibling of `sub_82B4F5F8`: the same prefix ladder (192/240/252/255) selects the width,
but the payload is zigzag-coded and the bias is halved.

Decoding, per width: the payload is halved with `srawi ...,1`, the prefix bits are masked out,
a bias is added, and if the **last** byte of the code has bit 0 set the result is negated with
`subfic r11,r11,-1` (`-1 - magnitude`, i.e. `~magnitude`). So 0 -> 0, 1 -> -1, 2 -> 1, 3 -> -2.
Biases 96, 6240 and 393216+6240 = 399456 are exactly half of the unsigned sibling's 192, 12480
and 798912. The 5-byte form (`b0 == 255`) is the exception: it assembles the four following
bytes into a raw 32-bit two's-complement value, with no zigzag, no bias, and it never reaches
the sign step.

Where the prefix bits are stripped differs per width and is worth reading in the source rather
than reasoning about: 2-byte clears 0x6000 **after** the halving (`rlwinm ...,0,19,16`), 3-byte
clears 0xF000 from the 16-bit pair **before** the third byte is appended (`rlwinm ...,0,20,15`),
4-byte keeps the prefix's low two bits as 0x30000 and masks the middle pair to 18 bits.

Write set: `{r4, 4}`, one `stw` on both store paths. Reads: the 1..5 code bytes, exact rather
than worst-case because the prefix byte is readable before the call. Gates 1-4 clean (leaf, no
callees, no timebase, result in r3 and in the store). `kReturnR3`.

Two exactness points.

`srawi` and `subfic` are 64-bit in the lifted form, and two of the `rlwinm`s have wrapped masks
(MB > ME), which RexGlue lowers with a 64-bit mask that leaves the low word duplicated in the
high half of the register. None of it is observable: the payload is at most 26 bits so `srawi`
never sign-extends anything negative, the biases cannot carry out of bit 31, `subfic`'s borrow
only propagates upward, and the only compared outputs are the `stw`'s low word and `r3`. The
port therefore keeps a `uint64_t` accumulator and casts at the store, and does not reproduce
the high-half garbage. If this ever diverges, that is the first assumption to re-test.

Verified before submission, outside the game: the port body was compiled standalone under
clang-20 against a byte-exact Python transcription of the lifted body (64-bit registers,
wrapped masks and all) over 16,777,216 inputs -- all 256 prefix bytes crossed with 16 boundary
values for each of the four payload bytes, covering every width and both sign parities. The
FNV hash of `(r3, stored word)` agrees exactly. That is a self-consistency check against my own
reading of the lifted form, not against the game; the shadow harness is what settles it, and the
`.inc` header carries its verdict.
