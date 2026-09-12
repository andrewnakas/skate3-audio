# sub_82B3D8E0

Runs one 256-word block through every track of a stream object. 375 lifted lines, 324500 calls per
boot, `RwAudioCore Dac`. Same object as `sub_82B3DB90`, `sub_82B3DC48`, `sub_82B3DD90`,
`sub_82B3DEA8` and `sub_82B3DF90`; their names are reused, and this file adds `+4` (the mixer
object), `+32` (a second cursor) and `+48` (the track count).

Arguments: r3 = the stream object, r4 and r5 = two buffer descriptors (`+4` data, `+14` stride — the
layout `sub_82B3CA60` also reads), r6 = an opaque value forwarded to the mixer.

Per track: build the six-word record at frame+80 — word 0 from r4's descriptor, word 5 from r5's,
words 2 and 3 zeroed — then loop: `sub_82B3DD90` fills words 1, 2, 4 and returns 256;
`mixer->fn(mixer, n, r6, track, record)` runs through a function pointer; the record's six words all
advance by `4 * n`; `sub_82B3DEA8` writes the block back into the ring. Repeat until 256 words are
done, then next track.

When `self[56]` is set, the first 128 words of each track go through the mixer **twice-shaped**: a
ramped pass with word 3 pointing into a 128-float table, then a flat pass for the remainder
(`offered - chunk`) with words 2 and 3 zeroed again. The table is built once at the top of the call,
at frame+112..frame+620, descending from the float at 0x822F9064 by the float at 0x820300D4
(`lis`-derived, loaded not assumed), and is addressed back to front as `frame + 624 - 4 * left`, so
the pointer walks forward as the ramp is consumed. Reads as a 128-sample crossfade over a buffer
transition, which is exactly what `sub_82B3DD90` uses the same flag for (a second segment).

Tail: `self[52] = max((self[52] + 256) mod self[20], self[24])` — with the compiler's two traps
(`twllei` on the divisor, `twlgei` on the overflow guard) kept, since `ppc_trap(type 0)` only warns
and returns; `self[36]` and `self[32]` both become `min(old + 256, self[20])` (the second with the
branch inverted, same result); `self[56]` is cleared.

Stores outside the frame: `self+52` u32 **twice** (the raw remainder, then the floored value),
`self+36` u32, `self+32` u32, `self+56` u8. Everything else is frame-internal: the record's six
words, the 128-float ramp, and the `stwu` back chain.

Result mask is `kReturnR3`, but that is honest only as a formality: there is no `li r3` on any path,
so r3 is whatever the last `sub_82B3DEA8` left, or the entry r3 when the track count is not
positive. The native body reproduces both cases by not writing r3, so a comparison would agree; no
caller is expected to read it. `kReturnNone` is not available here — with a false `Windows()` it
trips lint check 5.

Gate verdict: **gate 1**, and it is this function's own code: two `bctrl` at 0x82B3DA00 and
0x82B3DA8C through `*(self[4] + 0)`, a pointer read out of object state that no rewind can make
replayable. `sub_82B3DD90` is independently gate 2 and `sub_82B3DEA8` is verified, so neither is the
reason for the label.

Windows() returns false. Had the mixer been replayable, the write set would still be unbounded here
by way of the callees: the mixer writes through the record's segment pointers, which `sub_82B3DD90`
computes during the call (that is `sub_82B3DD90`'s own gate-2 wall), so this would be gate 2 as
well. The useful coverage of this function is piecewise: `sub_82B3DEA8`, `sub_82B3DC48`,
`sub_82B3DB90` and `sub_82B3DF90` are all verified through their own hooks.

Unsure: which of r4 and r5 is the input is not established — nothing here reads either buffer, only
computes a channel pointer into each, so they are named after their argument. `self[32]` is advanced
and clamped identically to `self[36]` (`sub_82B3DF90`'s cursor) but nothing in the family reads it,
so its role is unknown. `self[4]`'s `+0` is dereferenced once, so it is a function-pointer field or
a one-entry vtable; the code cannot tell which.
