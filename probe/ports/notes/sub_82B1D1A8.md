# sub_82B1D1A8

Leaf, 11 lines, no callees, no stores, no timebase. Argument: r3 = pointer to an 8-byte object
`{u32 +0, u32 +4}`. Returns in r3 `u32[r3+0] - u32[r3+4]` computed as a 64-bit subtract of two
zero-extended loads, so when the second field is the larger the borrow propagates into the upper
32 bits (`0xFFFFFFFF_xxxxxxxx`) rather than wrapping at bit 32. The port keeps that width and the
original load order (+0 then +4), which is the only subtlety in the function.

Structure unnamed: nothing in docs/rw_audio_structs.h has this shape, so no offset names are
invented. Direct sibling of the verified sub_82B1D198 (sum of the same two fields) and
sub_82B1D1B8 (signed product), and adjacent in address to them -- the three read as a small set
of arithmetic method slots over one 2-field object. Guess only, not asserted: a span or ring
cursor pair where the difference is a length/fill level.

Stores: none. Frame: none windowed (no guest-visible writes at all). Read set `{r3, 8}`, recorded
for replay only. Windows() always returns true.

Callers: no direct `sub_82B1D1A8(ctx` call exists in the lifted tree -- the address appears only
in skate3_init.h / skate3_init.cpp / skate3_register.cpp -- so it is reached through a function
pointer (a method slot), exactly like its two siblings. Any such caller reads the result by ABI
from r3, hence `kReturnR3`; gate 4 satisfied. r10/r11 are left unset by the port: they are
volatile and not compared (same as the verified siblings).

Gates: 1 pass (leaf), 2 pass (write set empty), 3 pass (no `mftb`), 4 pass (r3 named).
STATUS: pending. 77,900 calls in the boot profile on RwAudioCore Dac.
