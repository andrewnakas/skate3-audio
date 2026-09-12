# sub_82B3DB90

Non-leaf, 109 lines, 387,458 calls in the boot session, all on `RwAudioCore Dac`.
No stores of its own outside its frame -- everything it writes, it writes through memcpy.

Args: r3 = owner (`+20`/`+24`, whose difference in words is the ring's wrap span), r4 = ring
descriptor (`+0` base, `+4` end, `+12` cursor), r5 = destination, r6 = how many words back
from the cursor to start, r7 = words requested. Returns the word count actually planned.

Body: `r7 == 0` returns 0. Otherwise `want = min(r7, r6)` (signed), and the source is
`[r4+12] - 4*r6`; if that lands outside `[[r4+0], [r4+4])` it is moved on by
`4*([r3+20] - [r3+24])`. `run = min(want, ([r4+4] - src) >> 2)` words fit before the end of
the ring, so `memcpy(dst, src, 4*run)` then `memcpy(dst + 4*run, [r4+0], 4*(want-run))`, the
second source re-read from the ring after the first copy. Returns `want`.

Callee: `sub_82EDF460` is the XDK vector memcpy (byte loop under 16 bytes, else
lvx/vperm/stvx with dcbzl ahead of the stores; it calls `sub_82F52FB8` and `sub_82EE7460`,
both word/vector copy tails). It writes exactly `[r3, r3+r5)` -- the dcbzl addresses are
rounded up into the destination and then fully overwritten, and its own spills sit below its
r1. No locks, no allocation, no indirect calls; the census transitive gate 1 over the
closure {82EDF460, 82EE7460, 82F52FB8} is pass. Called through `GuestCall` on the live
context, so a future port of the memcpy is exercised too.

Windows: the two destination runs, `{r5, 4*run}` and `{r5 + 4*run, 4*(want-run)}`. Both
lengths are fixed in registers before the first copy, so the write set never depends on a
value produced during the call; only the second copy's *source* is re-read mid-call, and a
source does not move the write set. `MakePlan()` is shared by the body and the window
builder so the two cannot drift. Returns false when the two lengths together exceed the
32 KB cap (which is also what catches a negative `run`, since `rlwinm` turns it into a ~4 GB
length that the original would happily hand to memcpy), when a run would wrap 2^32, or when a
non-empty run starts at guest address 0.

Gates: 1 pass, 2 pass, 3 pass (no timebase), 4 pass -- the caller reads the word count in
r3, so the mask is `kReturnR3`.

Widths that matter here: `subf r4,r10,r11` is 64-bit, so a source below the ring base leaves
the high word set and that 64-bit value is what both the wrap add and the callee's r3 receive
(the compares and the store addresses are the only places it truncates). `add r3,r30,r27`
for the second destination is likewise 64-bit on two zero-extended words.

Unsure: `[r3+20]`/`[r3+24]` are read as counts because their difference is scaled by four
before being added to a byte address; nothing names them. `run < 0` should be unreachable
while the cursor stays inside the ring, but it is not checked by the original, and the
window builder refuses that case rather than declaring a 4 GB span.
