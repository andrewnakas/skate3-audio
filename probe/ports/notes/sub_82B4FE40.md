# sub_82B4FE40

Lifted: `skate3_recomp.68.cpp:55157`, 392 lines. The XMA input-buffer feeder. Called 134,627 times
during boot on `RwAudioCore Dac` -- the busiest gate-1 function found so far. `sub_82B50B78` is a
bare `b 0x82b4fe40` thunk to it, so everything here applies to that address too.

## Arguments

`r3` only: the System-side XMA object. Fields touched, all named for what this function does:

| offset | use |
|---|---|
| `+0x24` u32 | BYTE OFFSET from the object to the 24-byte segment table (`object + [+0x24] + 24*slot`) |
| `+0x30` u8 | segment slot, incremented then wrapped at `+0x32` |
| `+0x32` u8 | the wrap bound |
| `+0x34` u32 | -> the `rw_xma_stream` array (documented) |
| `+0x3C` u32 | bytes queued: pass B adds each stream's `remaining`, pass A subtracts each chunk fed |
| `+0x44` u32 | stream count (documented); re-read at the bottom of both loops |
| `+0x55` u8 | non-zero: reprogram every context once through `sub_82B4FC00`, then cleared |

## Shape

An infinite outer loop with two passes and two exits, both at `loc_82B4FEBC`:

1. **Pass A** (`loc_82B4FE6C`): for each stream, if both input buffers are still valid just
   `XMAEnableContext` and move on; otherwise enter the feed loop at `loc_82B4FF98`. That loop
   pushes `min(remaining, 0x800)` bytes of `stream->source` into the input buffer named by the
   select byte at `+0x19` via `sub_82B4FD40` (a 128-byte-block vector copy), re-arms the buffer,
   applies `+0x14` as a read offset in BITS plus 0x20 (one packet header) if it is strictly
   positive and then zeroes it, flips the select byte, and loops. `loc_82B4FF94` stores the
   advanced source and **falls through** to the top test, so one visit can fill both buffers in
   turn and keeps going until the source is empty or the next buffer is busy.
2. `loc_82B4FEBC`: **return** if `+0x3C` is non-zero (the streams still have work) or if the next
   segment's `+12` is zero (nothing to bind).
3. Bind the segment: advance and wrap the slot byte, and when `+0x55` is set call
   `sub_82B4FC00(object, [segment->data] & 3)` -- the low two bits of the segment's first word.
   `sub_82B4FC00` parks that in `XMA_CONTEXT_INIT.sample_rate`, which is XMA's 2-bit sample-rate
   code, not a rate in Hz. That resolves what `sub_82B4FC00.inc` called `kSampleRateField`.
4. **Pass B** (`loc_82B4FF4C`): `sub_82B50100(stream, index, segment, cursor)` per stream; the
   cursor advances by the callee's return value (bytes consumed) and each stream's new `remaining`
   is added into `+0x3C`. Then back to pass A.

## Stores

| address | size | mnemonic |
|---|---|---|
| `object+48` | 1 | `stb r10,48(r30)` and `stb r26,48(r30)` -- advance, then wrap to 0 |
| `object+85` | 1 | `stb r26,85(r30)` -- clears the reinit flag |
| `object+60` | 4 | `stw r7,60(r30)` twice (pass A, minus the chunk) and `stw r9,60(r30)` (pass B, plus remaining) |
| `stream+4` | 4 | `stw r6,4(r31)` at `loc_82B4FF94` -- the advanced source, shared by both arms |
| `stream+8` | 4 | `stw r9,8(r31)` -- remaining minus the chunk |
| `stream+20` | 4 | `stw r26,20(r31)` -- the pending start offset, consumed |
| `stream+25` | 1 | `stb r25,25(r31)` = 1 after buffer 0, `stb r26,25(r31)` = 0 after buffer 1 |
| `r1-144` | 4 | `stwu` -- own frame, with the `__savegprlr_25` spills inside it |

`stw r7,60(r30)` is a 64-bit `subf` truncated at the store and **nothing checks that `+0x3C`
covers the chunk**: if it does not, the field wraps to a huge unsigned value. Reproduced as-is.
Unlike Bug 3 there is no evidence it ever happens, only that nothing prevents it.

## Gate verdict

**gate-1, at depth 0.** Seven XMA imports, all of them hardware effects: re-arming an input buffer
(`XMASetInputBuffer0/1Valid`), moving the read offset, and the `XMADisableContext` /
`XMAEnableContext` pair around each push. A shadow replay would push the same 0x800 bytes into a
buffer the real run already handed to the decoder and re-enable a context mid-decode; no memory
rewind undoes that. `Windows()` returns false unconditionally.

Gate 2 would fail as well. The write set depends on `XMAIsInputBuffer0/1Valid`, which report
hardware state and are not readable from guest memory, so which streams are written -- and how
many times each -- cannot be predicted from entry state. Pass B's writes depend on
`sub_82B50100`'s return value. The census marks 13 stores `gate2_suspect`.

## Return mask

No `li r3,...` on any path. At `loc_82B500F8` r3 is whatever the last call left: an
`XMAIsInputBufferNValid` result, `sub_82B50100`'s byte count, or -- if the stream count is zero on
the first pass and `+0x3C` is non-zero -- the entry r3. Functionally void. `kReturnR3` is declared
because a gate-labelled port with `kReturnNone` and no `spec.write()` trips lint check 5; nothing
is compared either way.

## Uncertainties

- The seven imports are reached through their guest addresses (lint check 6 forbids naming an
  import thunk, and a kernel import has no port to route a `GuestCall` through). Unlike
  `sub_82B4FAF8.inc` this port does **not** write `ctr` first: a `bl` does not write `ctr`, so the
  bare `REX_CALL_INDIRECT_FUNC(constant)` form `sub_82B4FC00.inc` uses is the more faithful of the
  two spellings. `kXMAEnableContext`/`kXMADisableContext` agree with `sub_82B4FC00.inc`.
- `rotlwi r9,r11,1 ; add r11,r11,r9 ; rlwinm r11,r11,3,0,28` is written as `24*slot`. That is
  exact, not an approximation: `slot` comes from an `lbz` so it is at most 255, `3*slot` is under
  2^10 and cannot rotate into the low bits, and `24*slot` is already a multiple of 8 so the
  `0xFFFFFFF8` mask drops nothing.
- Whether the outer loop can actually spin is not established. A zero stream count sends pass B
  straight back to pass A with nothing changed, and if `+0x3C` is zero and the segment is ready,
  that is an unbounded spin. With a non-zero stream count the loop terminates because pass B adds
  each stream's `remaining` into `+0x3C`. Not reproduced as a bug fix either way.
- `+0x24` is an offset rather than a pointer: the table base is `object + [object+0x24]`, so the
  segment table is embedded in the object. Read from this one site.
- What `segment+12` means beyond "non-zero, so bind it" was not established, and `segment+0`'s
  first word is only known through its low two bits.
