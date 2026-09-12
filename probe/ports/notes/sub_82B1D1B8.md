# sub_82B1D1B8

Leaf, 11 lines, no stores, no callees. r3 = s32[r3+4] * s32[r3+0] as a full 64-bit product of
two sign-extended 32-bit loads (`mullw` on a 64-bit core; the lifted form does not truncate to
32 bits, so the product can occupy all 64 bits of r3 and is compared as such).

Argument: r3 = pointer to an 8-byte object {+0 u32, +4 u32}. Sibling of the verified
sub_82B1D198, which returns the sum of the same two fields; nothing in docs/rw_audio_structs.h
names the object, so no offset names are invented.

Stores: none. Read set `{r3, 8}`, recorded for replay only. Windows() always returns true.

Callers: no direct `sub_82B1D1B8(ctx` call in the lifted tree; the address appears only in
skate3_register.cpp / skate3_init.cpp, so it is reached through a function pointer (a method
slot). Every such caller reads the return value by ABI from r3, hence `kReturnR3`; gate 4
satisfied.

Gates: 1 pass (no callees), 2 pass (write set empty), 3 pass (no timebase), 4 pass (r3 named).
STATUS: pending. Called 208,517 times in the boot profile on RwAudioCore Dac.

Unsure of nothing material; the only subtlety is the width (64-bit product, not a 32-bit
truncated `mullw` result), which follows the lifted line exactly.
