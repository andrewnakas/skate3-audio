# Rust port — `skate-audio-formats`

First crate of the Rust side, at `rust/skate-audio-formats/`. Structured to drop into the
engine's workspace as `crates/skate-data/src/audio/` later: edition 2024,
`#![forbid(unsafe_code)]`, inline `#[cfg(test)]` tests, and the same split the existing
`abin` module states — *this module owns bytes and bounds checks; codec arithmetic belongs
elsewhere*.

Two modules:

- **`eb`** — EA "EB" v3 archives. Header, hash-sorted entry table, offset shift, and
  positional name reading, plus a `validate()` that checks every member lies inside the
  archive.
- **`eaac`** — EA Audio Core stream headers and block chains, with the bit layouts from
  the disc survey.

13 unit tests, all passing.

## What real data changed

Synthetic fixtures proved only self-consistency. Running against the user's own archives
corrected two things:

**The archive parser is right.** `wheels.big` and `ambience.big` both report a header
`total_size` matching the file on disk byte-for-byte (256,304 and 143,708,256), all members
validate inside bounds, and names read correctly in entry order.
`Whls_spins_Jump_1.snr` decodes as XMA, 1 channel, 48 kHz, 14.81 s — which independently
matches the bitrate arithmetic in the format survey.

**`Header::parse` was laundering garbage.** `.sns` block streams and `.sek` seek tables
carry no header at offset 0 — theirs live in a `.snr` sidecar or a companion archive's
metadata table. Parsing them returned a cheerful "5 channels at 384 Hz" instead of failing.
For a module whose stated job is bounds checking, silently producing a plausible-looking
struct from nonsense is worse than an error, because nothing downstream can tell.

`Header::check_plausible` now rejects sample rates outside 8–48 kHz, channel counts above
8, and zero-sample streams. Observed bounds across the whole disc are narrower still —
codec is always 3, rates are only 36000/44100/48000, channels only 1, 2 or 6 — so the
check is deliberately looser than the data to avoid rejecting something legitimate that
merely was not sampled.

Adding the check immediately failed one of my own tests, and the fault was the **fixture**,
not the check: I had invented an all-zero `header2` for the speech case, giving it zero
samples. Fixed the fixture to carry a realistic sample count rather than weakening the
validation.

## Container coverage — all three classes

| module | container | real-data check |
|---|---|---|
| `eb` | EA "EB" v3 archives | sizes match the file byte-for-byte, all members in bounds |
| `eaac` | stream headers, block chains, chunk splitting, `.sth` sub-sounds | 1384 ambience + 18 speech blocks, **every payload accounted for exactly** |
| `mus` | interactive-music segments | **all 8,179 segments** on the disc, every one matching the file's own SNR table |

33 unit tests, plus five `examples/` that run the same code over the user's own archives.

### The music container

Structurally distinct: the length field sits in a **12-byte block header** rather than
inline before each chunk, `size` counts the header itself, and flag `0x80` marks a
segment's final block.

The SNR table check matters because that table states each segment's sample count
independently of the block headers the walk uses. Agreement is a real cross-check, not a
self-consistency one.

#### The file header, and why "8 segments" was wrong

The SNR table offset and the segment count used to be command-line arguments, and the
value passed for the count was **8**. Eight is the constant at header `0x38`. It is not a
count of anything. The real totals are 1074, 5725 and 1380 — so the claim "8 segments,
all matching" rested on 0.1% of the data.

The header carries what was being passed by hand:

```text
0x04  u32 LE   segment_count          the format's one little-endian field
0x28  u32 be   unidentified           distinct per file
0x30  u32 be   snr_table_offset >> 4
0x34  u32 be   first_block_offset >> 7
0x38  u32 be   8 on all three files
```

`0x28` looked like the content hash the `.mpf` uses to name its `.mus`. It is not:
searching all three `.mpf` files for all three values, big- and little-endian, returns
nothing. It is recorded raw rather than named.

#### Segments are aligned, not searched

`next_segment_start` scanned: step forward four bytes at a time from the previous
segment's end until a block header parses. That is now a computation —
**segments begin on a 0x80 boundary** — because the scan was wrong.

It worked on `Game_Stream` and `World_Stream` by luck: their segments happen to end
4-aligned. `Ipod_Stream`'s end on every residue mod 4 (`0x3DCBD`, `0x9726F`, `0xC47D2`…),
and a scan anchored at an unaligned offset stepping by four can only ever visit offsets
congruent to its anchor. It never saw another header, so the walk stopped after
`Ipod_Stream`'s first segment and reported success — 1 of 1380 — because the one segment
it did walk matched.

That is the failure mode this project keeps meeting: **the check passed on the data it
reached, and said nothing about the data it never reached.** A partial walk that reports
only on what it walked is indistinguishable from a complete one unless the total is known
independently. The segment count from the header is what makes it falsifiable.

With the rounding rule, all three files walk end to end, and two of the three consume the
file to the last byte:

| file | segments | blocks | samples | bytes left over |
|---|---|---|---|---|
| `Game_Stream.mus` | 1074 | 13,981 | 68,717,547 | 0 |
| `World_Stream.mus` | 5725 | 108,034 | 535,970,668 | 0 |
| `Ipod_Stream.mus` | 1380 | 93,706 | 384,218,631 | 4 |

Consuming the file exactly is a stronger statement than any per-segment check: a wrong
stride would have to be wrong in a way that still lands on the final byte after 8,179
segments.

### On the value of the real-data examples

The unit tests use synthetic payloads and have never once caught a bug in this crate. The
`examples/` checks, running the same code over real archives, have caught four:

1. `Header::parse` accepting garbage from headerless `.sns`/`.sek` payloads
2. the `.snr` record being variable length (8 or 16 bytes), not fixed
3. the chunk length formula failing on every speech block
4. a stream's final block carrying alignment padding
5. `next_segment_start` scanning by 4 from an unaligned anchor, which silently truncated
   the `Ipod_Stream.mus` walk to its first segment of 1380

Synthetic fixtures prove the code is self-consistent, which is exactly what a wrong format
assumption preserves. Both kinds of test are worth having, but only one of them finds
things.

## Not yet done

- `.mpf` segment sequencing (the `.mus` container itself is done). Music is interactive,
  so "convert a music file" means segments plus the map that orders them, not one track.
- `BIG4` + `Viv4` pair used by `overlays.big`.
- `.abk` / `.bnk` bank containers; `.csi` remains unidentified.
- The offline transcode step. `ffmpeg` has an `xma2` decoder, but EA re-blocks the XMA and
  strips packet padding, so the block chain has to be reassembled into something ffmpeg
  will accept — that is the next real piece of work, and it is where the decompiled loader
  becomes necessary rather than optional.
