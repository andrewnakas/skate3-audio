# sub_82B1CE18

Leaf, 28 lines, no callees, no stores. Reads a small stack object at r3:
`+0` u8 capacity, `+4` s32 depth, entries u32 at `+4*(k+1)` for k = 1..depth (so `+8` is entry 1).
Returns in r3 the top entry `u32 [r3 + 4*(depth+1)]` when `0 < depth <= capacity`, else 0.
The `cmpw` against the `lbz` value is signed on a zero-extended byte, so capacity is 0..255 and
the entry offset is at most `+0x400`; `rlwinm r10,r11,2,0,29` is a plain 32-bit `<< 2` here.
Arguments: r3 = stack object only. Result: r3 (`lwzx` zero-extends; `li r3,0` on both reject paths).
Stores: none. Window: none; reads `{r3, 8}` and, on the in-range path, `{r3 + 4*(depth+1), 4}`.
Result mask: `kReturnR3`. No direct `bl` to this address exists anywhere in the lifted sources
(only `skate3_register.cpp` / `skate3_init.h` list it), so every one of its 2.29M boot calls
arrives through function-pointer dispatch; the ABI return register is the only thing a caller
can consume. Scratch r10/r11/cr6 are left untouched by the rewrite and are not compared.
Gates: 1 pass (leaf), 2 pass (no writes), 3 pass (no timebase), 4 pass (r3 named).
Hot: 2,293,752 calls in the boot profile on RwAudioCore Dac -- a full-session compare is cheap
(8-12 bytes of reads per call) but the census log volume may want a SAMPLE_SHIFT if it is noisy.
