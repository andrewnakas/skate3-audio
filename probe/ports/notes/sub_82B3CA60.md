# sub_82B3CA60

Delivers frames from a stream object into a caller's buffer descriptor. 338 lifted lines,
134290 calls per boot — the hottest function in this batch — `RwAudioCore Dac`.

Arguments: r3 = the stream object, r4 = the caller's descriptor, r5 = frames requested.
Returns frames delivered, in r3, as all 64 bits of the accumulator (see below).

Two shapes, chosen by `self[51]`:
- **nonzero** — the object owns a scratch descriptor at `self + u32(self+40)`. Whatever `self[44]`
  says is already pending there is copied out first (per channel, `sub_82EDF460`, four bytes a
  frame), then the loop refills the scratch through the function pointer at `self[20]` and copies
  again, until the request is met or the active entry's `+12` reads zero.
- **zero** — no scratch: the fill function writes straight into the caller's descriptor, and its
  return value is *discarded* — `add r27,r30,r27` credits what was asked for, not what came back.

Entry address, both shapes: `self + u32(self+36) + 24 * u8(self+49)`.

Stores: `self+44` u16, five times over the body (the refill result, then the result minus what was
copied out, on each of two paths); `scratch+12` u16 once. Nothing else outside the frame.
The frame is reproduced for the callees only — no `(r1)` slot is read by this body.

Integer width matters here and is not cosmetic: `r27` (delivered) and `r24` (requested) are only
ever *compared* as signed low words (`cmpw`), but the value returned in r3 is the full 64-bit
accumulator, and on the `mr r27,r5` path that is the caller's r5 verbatim, high bits included. All
four of those live in `uint64_t` locals with a `Word()` helper for the compares.

The reload at `loc_82B3CB9C` (`sth r11,44(r31)` ; `sth r11,12(r29)` ; `lhz r11,44(r31)`) is load
bearing, not redundant: `scratch+12` is `self + u32(self+40) + 12`, which *is* `self+44` when that
offset is 32, and then the second store overwrote the first. Reproduced as a reload.

Gate verdict: **gate 1**, and it is this function's own code, not only a callee's: two `bctrl`
through `self[20]` at 0x82B3CB80 and 0x82B3CCA0, whose targets are loaded object state and cannot
be replayed on rewound memory. `sub_82B3C9D8` adds four more indirect calls, and it is called on
every path that does any work. `sub_82EDF460` is outside the audio corpus (it behaves as a memcpy
with `r3` = destination); it is not the reason for the label.

Windows() returns false. Had it been written, the write set is two spans and enumerable from entry
state, so this is not also gate 2 — except that the scratch/caller descriptors may alias
(`sub_82EDF460`'s destination is the caller's buffer, whose address and length come from fields the
copy itself can move), which would need the aliasing check `sub_82B34BD0.inc` does. Moot under
gate 1.

Unsure: `+14` is named a stride because it multiplies the channel index on both descriptors; it is
also the cap on a single refill (`min(remaining, stride)`), which fits "one channel's worth" but is
not proof. `self[28]` is named "consumed" from `total - consumed` capping the refill; nothing here
writes it.
