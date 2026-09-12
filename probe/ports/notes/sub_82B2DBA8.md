# sub_82B2DBA8

Non-leaf, 356 lifted lines, 141,508 calls on the boot session, `RwAudioCore Dac`. Census gate-1
verdict: pass, closure of 4 (`82B43FB8`, `82EDF460`, `82F52FB8`, and `82EE7460` inside memcpy) --
no lock, allocation call, release, indirect call or timebase. Mask `kReturnR3`: `li r3,1` on both
exits.

Arguments: r3 = the voice, r4 = the stream. On the voice, all plain offsets: `rw_ptr +8` the system,
whose `+0` is an arena with a bump pointer at its `+32`; `u8 +42` channel count (reloaded at every
loop test); `f32 +64` the last stream rate this voice was set up for; `u32 +68` the 16.16 step;
`u32 +72` the 16-bit phase, held in the word's LOW half here and in the HIGH half inside
sub_82B43FB8's slot; `u16 +76` the offset of the per-channel tail rows within the voice; `u16 +78`
the output-frame cap; `u8 +80` input samples carried over from the last block; `u8 +81` the samples
the resampler must leave behind. On the stream: `+28`/`+32` the descriptor pair (sub_82B34E08's
shape), `rw_ptr +40` the format (`f32 +12` its rate), `u32 +48` input frames, `f32 +52` the rate the
voice compares against. Tail rows are six singles -- 24 bytes -- per channel (`addi r24,r24,24`,
`addi r21,r21,6`).

Behaviour: (a) if `[stream+52] != [voice+64]`, cache the stream's rate at `+64`, reset `[stream+52]`
from the format's rate, return 1 -- no resampling. (b) Otherwise take a scratch run off the arena:
`[arena+32] -= (4*input_frames + 151) & ~0x7F`, published for the duration of the call and restored
from the entry value at the end. Compute the output frames as
`(((available - bias + 1) << 16) - phase - 1) / step`, or 8192 when the step is zero, or zero when
`available - bias + 1 <= 0`, clamped by `[voice+78]`. Then per channel: memcpy the previous tail into
the front of the scratch run, memcpy `4*input_frames` of the source channel behind it, resample
`frames` singles into the destination channel through sub_82B43FB8 with the cursor and phase in this
frame's slots at r1+80/r1+84, and copy whatever the resampler did not consume into the channel's tail
row (four singles per trip, then a byte memcpy for the remainder). Finally store the leftover count
at `+80` (low byte only), the phase back at `+72`, swap `+28`/`+32`, store the frame count at
`[stream+48]`, reset `[stream+52]` from the format, restore the arena pointer, return 1.

The frame **is** reproduced (`stwu r1,-224`): r1+80 and r1+84 are sub_82B43FB8's cursor and phase
slots, and that callee spills into its own red zone below r1, so without the allocation both would
land in the caller's live frame, outside every window.

Window: the rate-changed path only -- two 4-byte stores, `voice+64` and `stream+52`, predicted from
entry state by the one fcmpu that decides it (neither single is written before the test). False when
`[stream+40]` is null, because the original loads the rate through it.

**The resample path is gate 2 and Windows() returns false on it.** Everything in it derives from
entry state except one length: each channel's tail row is written for `available - consumed` singles,
where `consumed` is the input cursor sub_82B43FB8 leaves at r1+80 -- a value that exists only during
the call. Bounding it by `available` instead is not acceptable: `available` is
`[voice+80] + [stream+48]`, so with a block of a few hundred input frames the window would reach a
kilobyte past the 24-byte tail row into unrelated fields of a live mixer object, and the harness
rewinds every window byte, which would clobber whatever another thread wrote there in the meantime.
Lifting the gate means predicting `consumed` exactly: the resampler's index advance telescopes to
`((phase + frames*step) >> 16)` as long as no group of eight overflows the 16-bit fraction field --
the same `8*whole + 8 <= 0xFFFF` guard sub_82B43FB8's own Windows() already uses for its read span --
after which the write is `[tail_row, tail_row + 4*(available - consumed))` per channel and the
remaining spans are the scratch run `[scratch, scratch + 4*available)`, the arena word, the
destination channels `[dst, dst + 4*frames)` each, and the seven tail words on the voice and stream.
That derivation is not landed here because a mispredicted length is a write outside the windows into
the running game, and nothing in this session could measure it.

Unsure of: whether the arena at `[[voice+8]+0]+32` is per-thread. It is decremented and restored
inside the call, so the harness can replay it once it is windowed, but if a second thread allocates
from the same arena between the lifted run and the rewind, the rewind would restore over that
allocation. Worth settling before the resample path is ever compared.
