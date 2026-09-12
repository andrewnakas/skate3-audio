# sub_82B1C7E8

Leaf, 90 lines, no callees, no imports, no timebase. ~95.6K calls per boot session on
`RwAudioCore Dac`. No `bl 0x82b1c7e8` anywhere in the lifted tree, and no `lis/addi` pair builds the
address (the three `-14360` hits use other `lis` values); it appears only in the function table, so
it is reached through a function pointer, like its neighbour sub_82B1C778. r3 is set by `li` on every
path immediately before `blr`: mask `kReturnR3`.

Arguments: r3 = 16-byte object (nothing in `docs/rw_audio_structs.h` names it): f32 accumulator +0,
u8 fired +4, s32 reset +8, s32 threshold +12.
Singles (image dump): 0.0f at 0x82165A10, -1.0f at 0x8216DEE0; 0x830775D8 reads 0.0f in the dump but
sits outside that rodata, so it is loaded live and treated as a variable step.

Behaviour: if +8 != 0 store 0.0 at +0. Else, if +0 < 0.0, store 0 at +4 and return 0 (no add).
Then reload +0; if +0 >= float(s32 +12) or NaN: store 1 at +4, -1.0 at +0, return 1. Otherwise
+0 = fadds(+0, step), store 0 at +4, return 0.

Stores, in order per path: reset path `+0`; then fire `+4, +0` or count `+0, +4`; idle path `+4` only.
The `std r9,-16(r1)` red-zone spill feeding `fcfid` is the function's own frame: not reproduced.
All four `disableFlushModeUnconditional()` points kept.

Window: `{r3,5}` unconditional. Reads: `{r3,16}` and the three singles.
Gates: 1 pass (leaf), 2 pass (5 bytes), 3 pass (the step is memory, not a timebase), 4 pass.
Unsure: whether 0x830775D8 is runtime data (the "step" name is a guess), and the caller identity.
