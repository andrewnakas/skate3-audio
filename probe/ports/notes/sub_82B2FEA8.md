# sub_82B2FEA8

Leaf, 138 lines, 4 calls in the boot profile, `RwAudioCore Dac`. r3 = an object with a table
pointer at `+1096`, r4 = six input floats, r5 = six output words, f1 = a scalar (read on every
point, never written). Returns 1 in r3.

The input block is the one `sub_82B2FE00` fills -- same pool, adjacent address, same six-word
shape (five ramp points at +0..+16 and a span at +20) -- and this function turns it into six
integers. For each point: `target = select(f1) * (ramp * kInputScale)`, where `select` is f1
itself when `f1 <= kThreshold` and the threshold otherwise; then it sweeps a 1652-entry
ascending float table at `u32[r3+1096]` for the first entry **greater** than the target,
reloads that entry, truncates it with `fctiwz` and stores the word at `r5+4i`. Then, if the
gain (`f1 * kHighScale` on the above-threshold path, otherwise the baseline constant) is
greater than the baseline, it reads the stored word **back out of memory**, widens it
(`extsw`/`std`/`lfd`/`fcfid`/`frsp`) and stores `fctiwz(word * gain)` over it.

Three behaviours that are easy to lose in a rewrite, all reproduced:

- The table cursor `r11` **persists across the six points**, so the whole call is one forward
  sweep. A point can therefore find nothing, and once the cursor reaches 1652 every later point
  skips the search entirely -- in which case the slot keeps whatever the caller left there, and
  the rescale step still runs on it.
- Only the LAST word is cleared on entry (`stw r11,20(r5)`); out[0..4] are not initialised.
- The table pointer is reloaded from `r3+1096` on every point, after this call's own stores, so
  it is not hoisted out of the loop.

Constants: pool base `0x822F8600` (`lis -32208 ; addi -31232`, the same base `sub_82B2FE00`
reads 468/472/476 from) with the input scale at +456, the threshold at +460 and the high scale
at +464; the baseline at `0x8231A844` (`lis -32206 ; lfs -22460`). All computed as
`((imm & 0xFFFF) << 16) + offset`, not read by eye.

Write set `{r5, 24}`: every store goes through r8, which runs r5, r5+4 .. r5+20, plus the entry
`stw` at +20. The `std r9,-16(r1)` is the function's own red zone, so it is not windowed.
Read set: the six inputs, the table pointer, the four constants and the **whole** table
(1652 * 4 = 6608 bytes) -- the sweep can reach any entry, and a recorded vector has to be
replayable. Windows returns false if the table pointer is null, which would make the original
sweep from guest address 0. Gates 1-4 clean (leaf, no callees, no timebase, r3 plus the stores).
`kReturnR3`.

Verified before submission, outside the game: the lifted body was copied verbatim into a
standalone driver with stub RexGlue macros and run against the port body on the same fake
memory -- 4,000 randomised trials plus 40 targeted scenarios covering table exhaustion, both
sides of both float compares, NaN inputs, NaN/inf/`3e9` table entries (the `fctiwz` saturation
paths) and an output block deliberately overlapping the table pointer to test the in-loop
reload. Zero disagreements in the six output words and r3. That checks the rewrite against my
own transcription of the lifted form, not against the game; the shadow harness is what settles
it, and the `.inc` header carries its verdict.
