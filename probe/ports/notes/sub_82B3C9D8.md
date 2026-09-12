# sub_82B3C9D8

Leaf, 70 lines, no callees, no imports, no timebase. ~134.5K calls per boot session on
`RwAudioCore Dac`. Three direct callers, all in the same caller (skate3_recomp.68.cpp:8289, 8431,
8503), each `mr r3,r31 ; mr r4,<count> ; bl` and then compares callee-saved r27/r24 or returns r27:
no caller reads r3 or any volatile register afterwards. Void: mask `kReturnNone`. The body never
writes r3 or r4, so they match anyway.

Arguments: r3 = object, r4 = amount to advance (only the low word matters).
Object (nothing in `docs/rw_audio_structs.h` names it): u32 position +28, u32 table byte-offset +36,
u8 index +49, u8 count +50. Segments are 24 bytes at `object + u32[+36] + 24*index`; +8 start, +12 end.

Behaviour: position += r4 (stored). If the new position != current segment's end, return. Else zero
that segment's end, index = (index+1) & 0xFF, wrap to 0 if index >= count (unsigned), then
position = new segment's start.

Stores, in order: `r3+28` u32; `seg+12` u32 (0); `r3+49` u8; `r3+49` u8 (0, wrap only); `r3+28` u32.
Reloads kept: +49 after the `seg+12` store, and +49/+36 again at loc_82B3CA34.

Window: `{r3+28,4}`, `{r3+49,1}`, `{seg+12,4}` with seg from entry +36/+49. The census flagged this
`gate2_suspect` because the store base r10 is derived; it is derived only from loads that precede
every store and is not recomputed before the store, so it is enumerable. Reads: `{r3,51}`, the
current segment's +8..+15, and the +8 word of segments (index+1)&0xFF and 0.

Gates: 1 pass (leaf), 2 pass (12 bytes, entry-derived), 3 pass, 4 pass (three stores).
Unsure: the field meanings (position/segment/end) are a reading of the arithmetic, not documented.
