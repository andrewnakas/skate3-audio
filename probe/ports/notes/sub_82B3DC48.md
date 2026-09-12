# sub_82B3DC48

Non-leaf, 184 lines, 266,878 calls in the promoting session (the package said 330,526 for an
earlier boot), all on `RwAudioCore Dac`. Shadow-verified clean and promoted.

Same family as `sub_82B3DD90` (its only caller), `sub_82B3DB90` (its only callee),
`sub_82B3DEA8` and `sub_82B3DF90`: all five take the same stream object in r3, all five run once
per block from the same caller. Object fields used here: `+8` the destination buffer, `+20`
span-high, `+24` span-low (read only by the callee's wrap normalisation). `sub_82B3DB90.inc`
already names `+20`/`+24` `kSpanHigh`/`kSpanLow`; the three new files use one name set across the
family.

Args: r3 = stream object, r4 = the 16-byte ring window `sub_82B3DD90` built on its frame (`+0`
base, `+4` end, `+12` cursor -- `sub_82B3DB90`'s `kRingBase`/`kRingEnd`/`kCursor`, with `+8`
stored but read by nobody in this family), r5 = the segment array, r6 = how many segments (1 or
2 from the only caller). Returns the destination pointer after every segment has been cut off it.

Segment entry, 16 bytes: `+0` need (words wanted, and the ranking key), `+4` cap (the caller
derives it from object `+16` plus 255 or 127), `+8` rank, `+12` out. This function writes `+8`
and `+12`; the caller reads `+12` back.

Body: `[segs+8] = 0` always. With two segments they are ranked by need -- if segment 0 needs
less than segment 1, slot 0 selects 1 and slot 1 selects 0, else the identity (and slot 0's zero
is stored a second time, reproduced). `running = roundup32([segs[rank0]+0])`. Zero or fewer
segments returns `[obj+8]` at once. Then once per segment, reading the rank out of
`segs + 8 + 16*i`: `need_up = roundup32(need)`, `pad = need_up - need`,
`cap_up = roundup32(cap + pad)`. If `need_up <= running`, the segment fits: `out = dest + 4*pad`
and `sub_82B3DB90(obj, window, dest, need_up, cap_up)`, after which
`running = need_up - returned`. Otherwise it does not: `out = dest + 4*(pad - need_up + running)`
and `sub_82B3DB90(obj, window, dest, running, max(running - (need_up - cap_up), 0))`, after which
`running = returned + running`. Either way `dest += 4*returned`.

Stores: `{segs+8, 4}` always; `{segs+24, 4}` when r6 == 2; `{segs[rank]+12, 4}` per segment; and
per segment the destination run `sub_82B3DB90` writes, `{dest, 4*returned}`.

Callees: `sub_82B3DB90` through `GuestCall`, so its own hook compares it and a promotion of it is
exercised here. It reaches only `sub_82EDF460` (the XDK vector memcpy, itself reaching
`sub_82EE7460` and `sub_82F52FB8`). Nothing in the closure allocates, frees, signals, submits,
locks or calls indirect; the census transitive gate 1 is pass.

Windows: the two rank words, the per-segment out word, and one span per copy. The ranking reads
only the two need fields, which this call never writes, so the ranks are predictable from entry
state; `MakeStep()` is shared by the body and the window builder, with the rank passed in (the
body reloads it from the slot as the original does, the builder supplies the predicted value).
`PredictCopy()` is the one duplication: `sub_82B3DB90` returns `min(r7, r6)` (signed, zero when
r7 is zero) and writes exactly `4*returned` bytes at `dest` as two back-to-back runs, so the
declared span is `{dest, 4*returned}` -- **but only while its first run is a sane word count**,
which needs the same source/wrap arithmetic `sub_82B3DB90.inc`'s `MakePlan()` does. That
arithmetic is replicated in `PredictCopy()`; **if `sub_82B3DB90.inc` changes, this must change
too.** The builder refuses (returns false) rather than guessing when: the first run would be
negative (which turns a `rlwinm` length into ~4 GB), the clamped count's low word is negative,
`4*want` exceeds the 32 KB cap, a non-empty run starts at guest 0 or would wrap 2^32, or a copy
would land on the segment array, the window or the object -- all three are re-read after each
copy, so a copy onto them would move the rest of the write set mid-call. Three or more segments
also refuse: the loop would read a rank word nothing in the call ever wrote.

Gates: 1 pass, 2 pass (with the refusals above), 3 pass (no timebase), 4 pass -- the caller
stores r3 at `out+16`, so the mask is `kReturnR3`. Worst case six spans, well under the 32 cap.

Widths that matter: `add r11,r11,r26` (the entry address), `add r9,r9,r10` (cap + pad),
`add r10,r10,r30` / `add r4,r9,r30` (the out pointers) and `add r30,r11,r30` (the destination
advance) are all 64-bit on zero-extended words, so a carry into bit 32 lives in the register and
is invisible in the stores; kept in 64-bit intermediates and cast only at the stores. The
`xoris`/`addc`/`subfe`/`and` quartet is a branch-free `max(left, 0)` on the low word that keeps
all 64 bits of `left` when it is not negative.

Unsure: `+0` and `+4` of a segment entry are read as word counts because both are rounded up to
32 and then scaled by four; nothing documents either, and "need"/"cap" are inferred from how
`sub_82B3DD90` fills them (`[obj+40]`/`[obj+44]` and `[obj+16] + 255`/`+ 127`) and from
`sub_82B3DF90.inc`'s reading of the same object fields. The `r6 <= 0` early return and the
three-or-more refusal are unreachable from the only caller.
