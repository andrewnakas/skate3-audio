# sub_82B2DAC8

Leaf, 141 lines, 225,251 calls per boot -- one of the hottest in the set. r3 = a voice, r4 = its
stream, r6 = the block length in frames.

Computes `ratio = (requested_rate / source_rate) * scale` from `voice+64`, the format's rate at
`u32[stream+40]+12` and `voice+52`. If the ratio differs from the one cached at `voice+60`, it
scales the ratio by a pool constant, rounds half away from zero, truncates, clamps the result at
262144, and stores the ratio at +56, the cache at +60 and the step at +68. On the clamp path the
stored ratio is a pool constant instead of the computed one.

The tail runs on both paths: it re-reads the step and the ratio from memory, multiplies the
step by the frame count as a full 64-bit product, adds the fraction at +72, stores the frame
count at +78, scales the stream's gain at +56, and returns the frames remaining -- the high half
of the low word, minus the byte at +80, plus the byte at +81, clamped to zero.

Write set: `{voice+56, 8}`, `{voice+68, 4}`, `{voice+78, 2}`, `{stream+56, 4}`, declared as the
union of both paths. The `fctiwz` spills at `r1-16` are the function's own red zone, so they are
not windowed. `kReturnR3`.

Two exactness points. The remaining-frames arithmetic is 64-bit with a borrow that leaves the
upper half set, while the sign test reads only the low word, so it cannot be narrowed to 32 bits.
And all four constant addresses were computed as `((imm & 0xFFFF) << 16) + offset` rather than
read by eye, after one misread digit in `sub_82B2FE00` produced this project's first shadow
divergence.
