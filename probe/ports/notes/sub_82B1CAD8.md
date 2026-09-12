# sub_82B1CAD8

Leaf, 328 lines, no callees, no timebase. Evaluates a sampled curve at a cursor's position and
caches the result. r3 = cursor `{+0 curve*, +4 last position, +8 cached value, +12 position}`;
curve `{+0 u8 type (2 = s16, 1 = s8, else s32), +2 u16 count, +4 s32 start, +8 s32 end,
+12 float scale, +16 samples}`. Names are readings from this function only; nothing in
`docs/rw_audio_structs.h` covers either object.

Paths: (a) `pos == last` (signed cmpw): return `u32[cursor+8]`, no store. (b) Otherwise store
`pos` to `+4`, clamp it to `[start, end]`, `index = pos - start`. If `scale == 1.0f`
(`fcmpu` against rodata `0x8231A844`): value = sample[index] sign-extended by type, stored to
`+8`, returned in r3 zero-extended (`rotlwi`); no bounds check. (c) Else: `i0 = round(index *
scale - 0.5)`, `i1 = min(i0+1, count-1)`, linear blend `s0 + (s1 - s0) * (index*scale - i0)`
with `fmadds`, rounded half away from zero via `fctiwz`, stored to `+8`, returned in r3 (the
negative branch reloads `+8` into r3; the same 32-bit value zero-extended).
Rodata: `0x8231A844` = 1.0f, `0x8209975C` = 0.5f, `0x82165A10` = 0.0f (read from the image
dump); the port loads them from the guest exactly as the original does.

Stores: `{cursor+4, 4}` (stw), `{cursor+8, 4}` (stw). The eight `std`/`stfd` to `-16(r1)` and
`-8(r1)` are the leaf's red-zone int<->float spills (census `gate2_suspect: 4` is these); not
reproduced, not windowed, per the brief. Window: `{cursor+4, 8}` on every path.
Reads: `{cursor, 16}`, `{curve, 16}`, the three constants, and the sample table `{curve+16,
count*elem}` capped at 4 KB -- a bound, not the exact pair, because the exact indices need the
float rounding, and the original reads past `count` freely on path (b).

Result mask: `kReturnR3`. No direct `bl` to this address exists in the lifted sources (only the
dispatch tables list it), so all 1,772,082 boot calls arrive by function pointer and r3 is the
only thing a caller can consume. Scratch r4-r11, f0/f8-f13 and cr6 are not compared.
Gates: 1 pass (leaf), 2 pass (two words at fixed offsets from r3), 3 pass, 4 pass (r3 named).
Widths: `subf r10,r9,r10` is 64-bit on zero-extended words but every consumer takes the low 32
bits (`rlwinm`, `extsw`, `.u32` addressing), so `uint32_t index` is exact; likewise `count-1`.
Unsure: whether `fctiwz` at exactly `INT_MAX + 0.5` and NaN ever occur -- reproduced branch for
branch from the lifted line, not from the ISA, so they match either way.
Hot: 1.77M calls per boot on RwAudioCore Dac; every call is shadowed (no SAMPLE_SHIFT). Reads
are at most ~4.1 KB per call on the table-read cap; if dump volume is a problem, lower the cap
or add a shift.
