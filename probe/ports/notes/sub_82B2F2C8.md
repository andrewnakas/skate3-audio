# sub_82B2F2C8

Leaf, 433 lines, 4 calls per boot on `RwAudioCore Dac`. `f1` = the parameter that selects a
curve segment, `r3` = the owning object, `r4` = six output singles (read back and rewritten),
`r6` = six input singles. `r5` is zeroed at entry, so it is not an argument. Returns `li r3,1`
on both exits, so the whole result is memory.

Four phases:

1. `f1` is placed against three edge singles at `0x821161A0` (+0 low, +4 mid, +8 high). That
   picks segment 0 or 1 and a scale constant (`0x822F8A60` or `0x822F8A64`), and the blend
   weight is `(edge - anchor) * scale`. Segment `s` selects the row pair at
   `0x82116218 + 72*s`, read at -68 and +4 off a walking cursor.
2. loc_82B2F338, nine iterations: copies the nine abscissae from `0x821161B0` into `-80(r1)`
   and writes `fmadds(row_a, w, row_b * (1 - w))` into the nine ordinates at `-44(r1)`. Both
   arrays are contiguous red zone, not windowed.
3. loc_82B2F380, six iterations: each input at `r6 + 4i` is located by walking up the
   abscissae, then interpolated between the two bracketing ordinates and stored at `r4 + 4i`.
4. If the singles at `r3+68` and `r3+360` differ: normalise `r4[0..5]` in place by
   `1 / max(r4[5] + headroom, r3+68)`, clear six envelope slots at `r3+516` stride 36, then
   walk two queues of three 60-byte reservation records at `r3+720` stride 180. A record
   publishes when `(s32)[rec+0] >= (s32)(((size + 35) & ~31) + [rec+4])`, where `size` comes
   from the stride-12 cursor at `r3+392` read at -4/+0/+4; the publish writes `[rec+20] =
   size+1`, `[rec+16] = 0`, `[rec+36] = 0` (byte), `[rec+12] = [rec+0]`, `[rec+32] = [rec+4]`.
   Record 0's store order is `20,16,36,12,32`; records 1 and 2 use `16,12,32,20,36`. Both
   orders are reproduced as emitted.

Write set: `{r4, 24}` always; plus, when the two levels differ, `{r3+516+36i, 4}` for i in 0..5
and `{rec+12, 25}` for the six records (`+12..+36` inclusive). 13 spans, 198 bytes. `kReturnR3`,
which is the constant 1 — the memory windows are the whole comparison.

Gates: 1 passes (leaf, no callees, no imports, no indirect calls). 3 passes (no `mftb`).
4 passes (stores plus `r3`). 2 passes with three guards: every loop-4 predicate reads words
this call never writes (`r3+68`, `r3+360`, `r3+388..411`, `rec+0`, `rec+4` — checked against
every write the function makes, none collide), so the write set is knowable from entry state
*unless* the caller aims the `r4` output array at one of those words. `Windows()` returns
false in exactly those three aliasing cases rather than guessing. The census's 20 gate-2
suspects are all `cls=loop` bases assigned inside the function, and every one resolves: 2 are
the red-zone scratch stores (`r1-80`, `r1-44`, the function's own frame), 2 are `r4 + 4i`, 1 is
`r3 + 480 + 36i`, and the remaining 15 are `r3 + 720 + 180q + 60r + literal`. Every trip count
is fixed at 9, 6, 6 or 2 by an `li`/`mtctr` pair, so none of the 20 is actually unenumerable.

Two things I was unsure of, both recorded rather than assumed:

- `Windows()` declares all six reservation records even though each publish IS predictable
  from entry state. The union costs six spans and a non-publishing record compares equal, so
  the extra precision buys nothing; if a divergence ever lands in loop 4, tightening this is
  the first thing to try, because it would distinguish "wrote the wrong value" from "took the
  wrong branch".
- The inner search at loc_82B2F38C is **unbounded** in the original: it walks up from `-76(r1)`
  until an abscissa is not below the value, running off the nine-entry array into the ordinates
  and then out of the red zone if the input exceeds every knot. Reproduced verbatim. It cannot
  hang under the harness — the lifted body runs first on the same data — but it is the one place
  a native promotion would inherit a real out-of-bounds read.

`0x8231A844` is loaded as `1 - x`, `1 / x` and a lerp weight, so it is almost certainly `1.0f`;
the value is never assumed, only loaded. `0x82165A10` is the `0.0f` word `sub_82B1CF50` and
`sub_82B2DAC8` already load. `add r10,r7,r10` in loop 4 is 64-bit on two zero-extended words and
can carry into bit 32; every consumer reads only the low word, so `Needed()` keeps the 64-bit
intermediate and truncates at the single point it is read. All seven constant addresses were
computed as `((imm & 0xFFFF) << 16) + offset`, not read by eye.
