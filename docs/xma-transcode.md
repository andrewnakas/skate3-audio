# The transcode gate — what stands between parsing and audible audio

Container parsing is done and validated. Turning a block chain into a `.wav` is not.
This file records what is established, what is not, and two corrections to an earlier
version of it.

## Established: how the game feeds the hardware

`sub_82B4FC00` is the only function in the subsystem touching `XMAInitializeContext`,
`XMASetInputBuffer0/1` and `XMAEnableContext`. It **loops**, walking an array at `+0x34`
with a count at `+0x44`, setting up one hardware context per element:

```c
ctx.input_buffer_0 = stream[1];   ctx.input_buffer_0_valid = 1;
ctx.input_buffer_1 = stream[2];   ctx.input_buffer_1_valid = 1;
ctx.output_buffer  = stream[3];
ctx.num_channels   = *(uint8_t *)(stream + 24) - 1;
```

An XMA context decodes at most a stereo pair, so a 5-channel ambience bed needs three
contexts. **A stream is therefore several independent XMA sub-streams**, not one.

`sub_82B4FE40` (and its near-duplicate `sub_82B50B78`) is the feeder. Per stream it holds
a source pointer, a remaining byte count, and a buffer-select flag, and it:

- pushes **0x800 (2048) bytes** at a time — the XMA packet size — alternating between
  input buffer 0 and 1;
- copies via `sub_82B4FD40`, which is a **plain VMX128 memcpy** (prefetch, vector
  load/store, scalar tail) — it performs no transformation whatsoever;
- sets the initial read offset to `stream[5] + 0x20`, and `XMASetInputBufferReadOffset`
  takes **bits**, so 0x20 is 32 bits — exactly one XMA packet header.

Because the copy is verbatim, whatever the block holds is what the hardware decoder sees.

## Correction 1: "the payload is not XMA2 packets" was overstated

An earlier version of this file asserted that, based on reading four bytes at
`block + 8` and getting an implausible packet header. That reasoning was weak — it assumed
the XMA data starts immediately after the 8-byte block header, which is exactly what is
not yet known.

A direct test for 2048-strided valid packet headers inside a block was **inconclusive**: a
5,727-byte payload can hold at most ~2.8 packets, so the longest strided run found (3) sits
at the noise floor of the test. The honest position is that the packet framing question is
**open**, not settled either way.

## Correction 2: the `audio_dump_path` shortcut is weaker than claimed

The earlier version suggested driving the recomp and capturing `audio_dump_path` to get
correct audio without reimplementing anything. That tap is the **final mix** — every voice
summed, post-pan, pre-fold — not per-asset audio. It cannot produce an isolated asset
library, which is what an offline conversion step needs. It remains useful as a reference
signal for comparing a whole scene, and that is all it was ever good for.

## The actual remaining unknown

Who fills each stream's source pointer and remaining-byte count from the block. The feeder
just chunks a contiguous buffer it is handed; the binding from block bytes to per-stream
buffers happens upstream and has not been located yet. That single link determines whether
the sub-streams are plain XMA packet runs (in which case conversion is mostly bookkeeping)
or need reframing (in which case it is a real project).

## Hunt for the binder — progress and dead ends

**Ruled out:** `sub_82B487A8` masks `0xffffff` and extracts a top byte, which looked like
block-header parsing. It is an **allocator** — the mask packs alignment flags into an
allocation descriptor and its `0x800` is an alignment, not a packet size. Recorded so the
same false lead is not chased twice.

**Why the call graph looked empty:** `sub_82B50B78` and `sub_82B50B80` have *zero* static
callers. They are reached through a plug-in's `process` function pointer, like everything
else in the scheduler, so grep and call-graph walks both come up dry. That is a property of
the architecture, not a gap in the corpus.

**Pinned:** `sub_82B50B80` strides the stream array by **0x1C (28 bytes)**, which fixes the
per-stream record size. It is now `rw_xma_stream` in `rw_audio_structs.h`, with the stride
itself asserted — the first draft padded to 32 and the assertion caught it.

**Still not found:** who writes `source` and `remaining` from the block. Text-grepping the
decompiled C is the wrong instrument here — the offsets involved (`+0x34`, `+0x3c`, `+0x44`)
are far too common to discriminate, exactly as `+0x30`/`+0xCC` were when hunting the command
ring consumer. The next step is to read `sub_82B50B80` properly, all 235 lines: it is the
root driver, it is indirectly dispatched, and it already demonstrably touches both the array
and its count.

## Reading `sub_82B50B80` — what it actually is

It is the **output drain**, not the input binder: it polls
`XMAGetOutputBufferWriteOffset` / `ReadOffset` per context, computes how many samples are
available, and pulls decoded PCM out. So the binder is still not located.

Two useful things fell out of reading it properly.

**Per-stream fields now confirmed** (added to `rw_xma_stream`, all asserted):

| offset | field | evidence |
|---|---|---|
| +0x0C | output write cursor, wraps at 0x1800 | drain arithmetic |
| +0x10 | sample credit (see below) | setup accumulates, drain decrements |
| +0x18 | **channels this context decodes** | confirmed *twice*: `sub_82B4FC00` writes `ctx.num_channels = this - 1`, and the drain computes bytes as `channels * samples * 2` (16-bit PCM) |

**A segment list, purpose not yet established.** The driver walks an array embedded in its
own object -- note `*(int *)(param_1 + 0x24) + param_1`, an *offset* into the object rather
than a pointer -- with stride 0x18, indexed by a byte at `+0x31`:

```c
seg = param_1 + *(int *)(param_1 + 0x24) + *(uint8_t *)(param_1 + 0x31) * 0x18;
if (seg->end == 0) seg = NULL;              /* +0x0C */
skip = (seg->flag /* +0x14 */ == 0) ? 0x180 : 0;
remaining = seg->end - seg->start;          /* +0x0C - +0x08 -> param_1 + 0x48 */
```

### The segments are sample ranges, not byte ranges

Reading the setup and the drain together exposed an apparent contradiction in field +0x10:
the setup *accumulates byte-looking quantities* into it, while the drain treats it as a
count to multiply by `channels * 2`. Both readings cannot be right.

They reconcile if the segment table stores **sample positions**:

- `remaining = end - start` is then a sample count;
- `+0x10` is a per-stream **sample credit**, accumulated when a segment is bound and
  decremented as the drain consumes it;
- `channels * credit * 2` is then correctly bytes of 16-bit PCM.

Two magic numbers support this. The alignment arithmetic (`>> 9`, `* -0x200`) rounds to
**512**, which is the XMA frame size in samples. And the conditional skip is **0x180 = 384
= three 128-sample subframes**, which has the shape of a decoder priming skip.

This is an **inference**, not a confirmed reading -- it is the only interpretation found
that makes both uses of the field consistent, which is suggestive but not proof. It is
cheap to settle empirically: hook the feeder in the recomp, log the actual values, and see
whether they track sample counts or file offsets.

Searching for who writes `+0x24`/`+0x31` returned the same undiscriminating noise as before
-- those offsets are common on unrelated objects. The next probe should be the *input*-side
counterpart of this drain rather than another grep.

## MEASURED: the framing is mixed

The probe (`src/skate3_audio_probe.cpp`, hooking the feed memcpy) settled this empirically.
Raw capture in `out/reference/xma_feed_probe.txt`; 24 feeds during ordinary gameplay.

**Two concurrent streams, with different framing, from two different source buffers.**

| | stream A | stream B |
|---|---|---|
| source range | `0x4B19xxxx` | `0x49C3xxxx` |
| feed length | **always exactly 2048** | **variable, 45 - 2048** |
| leading word | varies | `08000000` (17/18), `22000000` (1/18) |
| XMA2 `metadata` field | **1 — valid packet header** | 0 — not a packet header |
| contexts fed | 2 | **3** |
| count | 6 of 24 | 18 of 24 |

Stream A is **conventional XMA2 packet framing**: fixed 2048-byte packets, source advancing
by exactly 0x800, and a valid packet header at the start of each (`metadata == 1`, frame
counts of 14-15). Those are directly consumable by any XMA2 decoder.

Stream B is EA framing: variable chunk sizes, a constant `08000000` prefix word, and the
source advancing by `len + 4` — a 4-byte inter-chunk quantity the copy does not include.

**Three contexts for stream B** confirms the multichannel split predicted from
`sub_82B4FC00`: 3 contexts x 2 input buffers each, the destinations landing on
`E2FC3000/3800`, `E2FC4000/4800`, `E2FC5000/5800`. Three stereo-capable contexts is the
5-channel ambience bed measured from `ambienceresident.big`.

### Two of my earlier claims were wrong, in opposite directions

1. "The payload is not XMA2 packets" — **wrong for stream A**, which is textbook XMA2.
2. The later retreat to "framing is an open question" was too pessimistic: it is now
   measured, and the answer is simply that **both framings are in use simultaneously**.

Neither hypothesis was right because both assumed the format was uniform. It is not.

### What this means for conversion

Conversion is not one problem. Assets carrying stream-A framing need no reconstruction at
all -- lift the 2048-byte packets and decode. Assets carrying stream-B framing need the
`08000000` prefix and the 4-byte inter-chunk gap understood first, which is now a small,
well-scoped question rather than an open-ended one.

No feed ever exceeds 2048 bytes in either class, so the packet size is a hard ceiling on
both paths.

## SOLVED: the block-to-substream binding

Five ticks of searching for "who binds block bytes to per-stream buffers" ended by
measuring the feed and then matching it back to the file. Both agree.

### Evidence 1 — the runtime feed is one packed sequence

Sorting the 18 stream-B feeds by source address shows a contiguous region with a strictly
repeating gap pattern:

```
gap histogram: {4: 11, 12: 5, 0: 1}
pattern:       4, 4, 12, 4, 4, 12, 4, 4, 12, 0, 4, 4, 12, ...
```

`[4, 4, 12]` is one round over three contexts. The 12 is `4 + 8`, and **8 is exactly the
`.sns` block header size** already decoded -- so the round closes at a block boundary.

(An earlier note claimed the source advances by `len + 4`. That is true only *within* a
round; consecutive feeds go to different contexts, so across the whole capture it held for
just 7 of 17 pairs. Sorting by source is the view that makes the structure visible.)

### Evidence 2 — the arithmetic closes exactly on disk

Walking real blocks of `08_univ_mt_low.sns`:

| block | payload | 4 + chunk0 + 4 + chunk1 + 4 + chunk2 | matches |
|---|---|---|---|
| 0 | 5727 | 4 + 2232 + 4 + 2328 + 4 + 1155 | **5727** |
| 1 | 5960 | 4 + 2337 + 4 + 2431 + 4 + 1180 | **5960** |
| 2 | 6050 | 4 + 2413 + 4 + 2451 + 4 + 1174 | **6050** |

Exact to the byte, on three independent blocks.

### The layout

```
block:   [u32 flags<<24 | size][u32 num_samples]      <- 8 bytes
payload: [u32 bit_offset][chunk 0]
         [u32 bit_offset][chunk 1]
         [u32 bit_offset][chunk 2]                    <- one chunk per XMA context
```

Chunk count is the context count, `ceil(channels / 2)` -- three for the 5-channel ambience
bed, matching the three contexts observed at runtime.

### The 4-byte fields are bit offsets

Each `u32` gives the bit offset of the first complete frame in the chunk that follows. For
block 1 they are 9367, 9743, 4739, each comfortably inside its chunk's bit length (18696,
19448, 9440).

This is what the decompiled feeder needs and could not otherwise have obtained:

```c
XMASetInputBufferReadOffset(ctx, stream->start_bits + 0x20);   /* takes BITS */
```

`start_bits` is `rw_xma_stream + 0x14`, and `0x20` is one packet header. Two independent
lines of evidence -- a field that demanded a bit offset, and a file field whose values are
valid bit offsets -- meeting at the same place.

**Status: CONFIRMED by decoding.** A single chunk, extracted with these boundaries and
wrapped in a RIFF XMA2 container, decodes in ffmpeg with **zero errors** and yields
**exactly the sample count the block header declares**:

```
block 0 header num_samples : 4736
ffmpeg decoded frames      : 4736
L: peak 2887  rms -30.1 dBFS      R: peak 3640  rms -28.7 dBFS
channels differ -> genuine stereo, not duplicated mono
```

Sample-exact agreement between a field parsed from the container and the output of an
independent decoder is not something a wrong split produces.

### What the failed first attempt taught

Concatenating all of a context's chunks and declaring a uniform 2048-byte block align
decodes ~23 KB and then desyncs (`broken frame`, `would have to skip 17426 bits`). That is
the expected result if each chunk is **independently framed** -- which is exactly why every
chunk carries its own bit offset. Chunks cannot be blindly concatenated; each must be
handed to the decoder as its own unit.

**One honest caveat:** ffmpeg located the frames itself, so the decode does not directly
prove the `u32`s *are* bit offsets. It proves the chunk boundaries are right and the chunks
are valid XMA2. The bit-offset reading remains the best explanation for those fields --
their values are valid bit offsets into the chunks that follow, and the feeder demands a
bit offset it has no other source for -- but it is corroborated, not demonstrated.

### Conversion recipe — complete and sample-exact

**Correction.** An earlier version of this section called the recipe "validated". It was
validated on *one chunk*. Running it across 12 blocks exposes two problems that a
single-chunk test cannot show.

**1. Independent per-chunk decoding loses exactly 64 samples per chunk.**

| block | declared | decoded | deficit |
|---|---|---|---|
| 1-5 | 5120 | 5056 | **64** |

Steady and exact. 64 samples is XMA decoder priming: restarting the decoder on every chunk
throws away its warm-up each time. The hardware never pays this because it feeds one
continuous stream into alternating input buffers, so decoder state carries across chunks.
This is precisely what the `0x180` (384-sample) skip constant in `sub_82B50B80` is about.

Block 0 loses **nothing** (4736 of 4736) while every later block loses exactly 64. That is
MDCT overlap: the first frame after a decoder restart needs the previous frame's state,
which a stream-start chunk carries and a mid-stream chunk does not.

**Concatenation is ruled out as a fix.** Joining a context's chunks across blocks and
decoding once yields only the first chunk's samples and then fails
(`num_vec_coeffs 668 is too large`). The chunks really are separately framed.

So the only correct fix is a decoder that **keeps state across chunks** -- one
`AVCodecContext` per context, fed packets from successive chunks. `ffmpeg` as a subprocess
cannot do that.

**FIXED by `tools/xma_decode.c`**, which does exactly that: allocates one decoder, submits
each chunk as its own `AVPacket`, and flushes at the end. Measured over the same 8 blocks:

```
declared                        40576
per-chunk restart (ffmpeg CLI)  40128   deficit 448
persistent decoder, context 0   40576   deficit 0
persistent decoder, context 1   40576   deficit 0
persistent decoder, context 2   40576   deficit 0
```

Zero deficit, zero failed chunks, all three contexts agreeing exactly. The priming loss is
gone and conversion is **sample-exact**.

**2. The marker scan can pick a wrong split that still balances. FIXED.**

Block 0 decoded 448 samples against 4736 declared. The cause is a defect in
`split_payload`: block 0's payload contains a **false-positive marker** at offset 2052, and
the split `[4, 2052, 2240]` *does* account for the payload exactly
(`4+2044+4+184+4+3487 = 5727`) while being wrong. The correct split is `[4, 2240, 4572]`,
which also balances.

So the arithmetic check is **necessary but not sufficient** — it cannot disambiguate when
spurious markers appear.

The fix is to enumerate every balancing split and **pick by decoding**: the right split
reaches the declared sample count, a wrong one falls far short. `tools/eaac_decode.py` now
does this. Measured over 8 blocks of the ambience bed:

```
before:  per-context [59840, 56064, 56064]   contexts disagree -> split was wrong
after:   per-context [40128, 40128, 40128]   contexts agree exactly
declared 40576, decoded 40128, deficit 448 = 7 mid-stream chunks x 64 priming
```

Every sample is now accounted for: the only shortfall is the known priming loss, and the
three contexts agreeing exactly is itself the signature of a correct split. Ambiguity is
occasional rather than pervasive — block 0 had three balancing splits, blocks 1 and 2 had
one each.

### The recipe

1. Walk the block chain (`{flags<<24|size, num_samples}` headers).
2. Split each payload into `ceil(channels / 2)` chunks.
3. Decode **each chunk independently** -- do not concatenate first.
4. Append the resulting PCM per context, then interleave contexts into the final layout.

A 5-channel bed splits 2 + 2 + 1, which the sub-stream sizes corroborate: contexts 0 and 1
came out at 97,304 and 92,987 bytes and context 2 at 47,692, about half, as a mono context
should. `tools/extract_substream.py` performs steps 1-2 and split 40 of 40 consecutive
blocks with the arithmetic closing exactly on every one.

Remaining gap: chunk **lengths** are located by scanning for the start marker rather than
read from a length field, because no length field has been identified -- the game gets the
length from state set up outside the block. The scan is self-checking (a block whose spans
do not account for the payload exactly is reported, not silently accepted) and has not
failed yet, but it is a heuristic and should be replaced if the real field turns up.

## Better plan than reimplementing XMA

The SDK already contains a working, Xenia-derived XMA decoder — `XmaContext`, backed by
libavcodec, in `third_party/rexglue-sdk/src/audio/xma_context.cpp`. A standalone tool that
links it and feeds it the per-stream sub-streams would reuse proven code rather than
rebuilding packet reconstruction from scratch. That is the path to prefer once the binding
above is known.


## End-to-end result

Retail archive to playable multichannel audio, with every sample accounted for:

```
ambience.big -> 08_univ_mt_low.sns -> 40576 frames x 5ch @ 48 kHz
ch0 -30.0 dBFS   ch1 -29.5   ch2 -28.3   ch3 -37.0   ch4 -35.0
```

The level distribution is itself a sanity check: three louder channels and two quieter ones
is what a 5-channel ambience bed should look like, and it falls out of the 2+2+1 context
split rather than being imposed.

### The pipeline

| stage | tool |
|---|---|
| archive directory, stream headers | `rust/skate-audio-formats` (`eb`, `eaac`) |
| block chain, chunk split (decode-verified) | `tools/eaac_decode.py --dump-chunks` |
| persistent-state XMA decode | `tools/xma_decode.c` |
| interleave contexts | `tools/eaac_decode.py` |

### Known remaining weakness

Chunk **lengths** are still located by scanning for a start marker, disambiguated by
decoding, because no length field was ever identified. It works -- ambiguity is occasional
and decode-verification resolves it -- but it is a heuristic, and decoding every candidate
split makes conversion slower than it needs to be. If the real length field turns up, both
problems go away.


## Generalisation: tested across asset classes

The pipeline was developed on the ambience bed. Testing it elsewhere matters, because a
recipe validated on one class is not a recipe.

| class | channels | rate | contexts | chunk marker | result |
|---|---|---|---|---|---|
| ambience (`.sns`) | 5 | 48000 | 3 | `08000000` | **40576 / 40576 exact** |
| speech (`.dat`) | 1 | 36000 | 1 | `60000100` | **114304 / 114304 exact** |
| music (`.mus`) | 2 | 44100 | 1 | `08000000` | block header differs -- not yet decoded |

Speech is a genuine generalisation test rather than a repeat: different channel count,
different sample rate, a different number of contexts, and **a different chunk marker**.
It still lands sample-exact, decoding to -15.9 dBFS (speech-loud, against ambience at -30).

Note the marker difference. `60000100` is not in the `MARKERS` set the splitter scans for,
and speech decodes anyway because a mono stream has one context, so there is nothing to
split -- the payload after the 4-byte bit offset *is* the chunk. The marker scan is only
exercised on multi-context streams. That is a latent fragility: a multi-context stream
using an unlisted marker would fail, and the marker set is empirical
(`0x08`, `0x22` observed) rather than derived.

### Music — SOLVED

The `.mus` block header is **12 bytes**, and unlike `.sns` the size field **includes the
header**:

```
[u32 flags<<24 | size]   size counts the 12-byte header itself
[u32 num_samples]
[u32 bit_offset]          same role as the .sns per-chunk offset
[body ...]                starts with the 08000000 chunk marker
```

Flag bit `0x80` marks the **last block of a segment**. Walking with that rule:

| segment | blocks | samples | duration | SNR table declares |
|---|---|---|---|---|
| 0 | 14 | 70560 | 1.600s | **70560** |
| 1 | 14 | 70560 | 1.600s | **70560** |
| 2 | 14 | 70560 | 1.600s | **70560** |
| 3 | 14 | 70560 | 1.600s | **70560** |

Every segment matches the count declared in the file's own SNR table -- an independent
field, not one used to derive the walk. Segments are separated by a constant **64 bytes**
of padding after the flagged block.

An earlier note guessed a 16-byte header; that was wrong. The leading `00000000` was
unrelated padding, not a header field. The give-away was that `header + size` landed
exactly on the next header once the header was taken as 12 bytes and the size read as
inclusive.

This also supplies the **length field that `.sns` appears to lack**: music states each
block's size explicitly, where the `.sns` path still needs a marker scan. Whether `.sns`
carries an equivalent field somewhere not yet read is now worth revisiting.

### What is still open for music

`.mus` is not an EB archive and does not start its audio with the `.sns` block header. At
the first non-zero byte past the SNR table the bytes run:

```
07fb 0000 1280 0000 1fce | 08000000 | 099ffc01 c0010203
```

The tail is the **same chunk signature** as ambience (`08000000`, then `XXXXfcYY`, then
`c0010203`), preceded by what looks like a bit offset (`0x1fce` = 8142). So the chunk-level
work carries over; what differs is the block framing ahead of it, which has not been
decoded. Music also sits behind a `.mpf` segment map, so playback order is a separate
question from decoding.

**Status: all three container structures decoded. Ambience and speech convert
sample-exact end to end; music's block and segment structure is validated against its own
SNR table but has not yet been run through the decoder.**


## The length field — found, and a correction

The `u32` before each chunk was documented above as a **bit offset**. That was wrong.
It encodes the chunk's **length**:

```
ambience (.sns)   chunk_length = (field - 19) / 4
music    (.mus)   body_length  = (field - 18) / 4
```

Exact on 60 consecutive ambience blocks and every music block tested. The same relation
with a bias differing by one, so the encoding is shared across containers.

The bit-offset reading was plausible because the values *are* in the right numeric range
for bit offsets into the chunks that follow, and because the feeder genuinely needs a bit
offset it had no other visible source for. But a real bit offset cannot be a pure function
of chunk length, and this is: `field = 4 x length + bias`, with no residual. The
coincidence held up for several ticks because it was only ever checked for plausibility,
never for a functional relationship to length.

(What the feeder's `start_bits` is actually fed remains unresolved. It is no longer safe to
assume it comes from this field.)

### What this removes

The splitter previously scanned for chunk-start markers and, when several splits balanced,
decoded every candidate to see which reached the declared sample count. That worked but
was slow, relied on an empirically observed marker set (`0x08`, `0x22` -- speech's
`0x60` was never in it), and could not distinguish two balancing splits without decoding.

The split is now deterministic: read the field, take the length, move on. Re-run over
**40 blocks** -- five times the earlier coverage:

```
context 0   204416 / 204416 declared   0 failed
context 1   204416 / 204416 declared   0 failed
context 2   204416 / 204416 declared   0 failed
```

The marker set, the ambiguity, and the decode-to-disambiguate pass are all gone.

## Final state

| class | container | conversion |
|---|---|---|
| ambience `.sns` | EB archive + sidecar header | **sample-exact** |
| speech `.dat` | EB archive + nested `.sth` sub-sounds | **sample-exact** |
| music `.mus` | segment chain + SNR table | **sample-exact** |

All three decode with every sample accounted for, through a deterministic split and a
persistent-state decoder.

### Refinement: the field is the data length, the size is the stride

An assertion added while checking music failed on the **last block of each segment**, which
is a real edge case rather than a broken formula:

| | mid-block padding | last-block padding |
|---|---|---|
| segments 0-5 | **always 0** | 48, 34, 16, 51, 7, 54 |

So a block's `size` is its stride and the length field is its *data* length; they agree
exactly except on the final block of a segment, which is padded out to an alignment
boundary. Use the field to bound the data and the size to advance. Every segment tested
runs 14 blocks and 70560 samples, matching its SNR table entry.

Worth noting the assertion is what surfaced this. The formula had been checked on 60
ambience blocks and the first dozen music blocks -- none of which were segment-final -- and
would have silently fed 7-54 bytes of padding into the decoder on every segment boundary.


## The length encoding, corrected twice

The `u32` before each chunk has now been read three ways. Recording the sequence because
each wrong reading was consistent with the evidence available at the time.

**First: a bit offset.** The values land in the plausible range for an offset into the
chunk that follows, and the feeder genuinely needs a bit offset it has no other visible
source for. Wrong: a bit offset cannot be a pure function of chunk length, and this is one.
It survived because it was only ever checked for plausibility.

**Second: two per-container biases.** `(field - 19) / 4` fit ambience exactly on 60
consecutive blocks; `(field - 18) / 4` fit music. Both exact, so it looked like two
encodings. Wrong: it is one encoding with a flag.

**Third, and holding:**

```
length = (field - 18) >> 2
```

The low two bits are not part of the length. They are **constant within a stream** and
differ between streams -- ambience payloads always leave a remainder of 1, speech and music
always 0. The parity of the raw fields is the tell: ambience's are uniformly odd, the
others uniformly even.

Measured over 2000 ambience blocks plus every speech and music block tested, with no other
remainder value seen. What the flag *means* is not established.

### Padding on a stream's final block

Splitting was also requiring the chunks to account for the payload exactly. That holds for
every block except the last of a stream, which is padded to an alignment boundary:
19 and 26 bytes observed on speech and ambience, 7 to 54 across music segments. The
splitter now tolerates a small trailing pad and still rejects a larger shortfall.

### Why this was caught

The Rust unit tests use synthetic payloads and passed throughout -- they only ever proved
the code agreed with itself. Running the same code over the real archives failed
immediately: all 18 speech blocks, and the final ambience block. The speech failure was
possible because that class had been validated *before* the length field was found, back
when a mono stream meant the splitter had nothing to split, so the formula had never
actually run on it.

After the fix, on real data:

```
ambience  1384 blocks   0 failed   every payload accounted for exactly
speech      18 blocks   0 failed   every payload accounted for exactly
```


## The `.mpf` sequencing map — top-level structure

Music is interactive: the `.mus` holds segments, and a companion `.mpf` says how they are
sequenced. The container's top level is decoded; most section *contents* are not.

```
+0x00  "PFDx"
+0x04  05 03 ...          version 5.3
+0x0C  four byte-sized counts (meaning unknown)
+0x10  u32 (unknown)
+0x14  u32 offset[10]     ascending; offset[0] is always 0x48 = the header size
```

Nine sections follow. The table validates hard: **the last offset equals the file size
exactly** in every file checked, and offsets ascend throughout. Trailing offset slots are
zero-filled.

### Sections identified

| section | evidence |
|---|---|
| 4 | ASCII identifiers -- a name table |
| 7 | contains the companion `.mus` **content hash**, plus an offset into it |
| 8 | exactly **8 bytes per segment** (1074 segments -> 8592 bytes, exact) |

Section 7 is the useful one for wiring the two files together: it carries the same content
hash the `.mus` stores in its own header, so a map can be matched to its stream rather than
assumed by filename.

Section 8's first field ascends monotonically across the whole file, which is consistent
with a timeline position. Its second field is **not** identified.

### A correction made in passing

The second field looked like a duration in milliseconds: the first six records all read
1600, and the measured segment length is 70560 samples at 44.1 kHz = exactly 1600 ms. That
was coincidence. A histogram over all 1074 records shows the field varying widely
(1297, 1454, 1333, 1188 ...), so whatever it is, it is not a constant segment duration.

Reading the first few records and generalising is the same mistake that produced the
bit-offset reading and the two-bias reading of the length field. The check that catches it
is always the same: look at the whole distribution, not the head of it.

### Measured 2026-09-12: structure of sections 0-8, from all three files

Three `.mpf` files exist on disk (`game`, `ipod`, `world`), and the header verifies from raw
bytes rather than from this document's prose: `50 46 44 78` = `"PFDx"`, version `05 03`, an
**undocumented constant `0xB003` at +0x06** identical in all three, the four count bytes at
`+0x0C`, the `u32` at `+0x10` (525,498 / 198,724 / 136,945), and `offset[10]` at `+0x14`. The
documented invariants hold in every file: `offset[0] == 0x48`, offsets ascend, and the last
equals the file size exactly.

**Section 4 is 20-byte records** — 160/20 = 8, 60/20 = 3, 40/20 = 2, exact. Each record is a
small NUL-separated string pool, and the contents are the interactive-music parameter namespace:
`numchasers`, `numracers`, `resumenode`, `chaser`/`racer`, alongside section names
`chasesection`, `racesection`, `raceoverlay`, `ipodsection`, `djsection`, `replay`. (An earlier
pass read these as broken strings; they are multiple fields in one record. `world` also carries
binary `c5 b0` at +0x0A, so the record is not purely text.)

**`counts[3]` at +0x0F is section 2's element count** — 15, 3, 5 against `0x0F`, `0x03`, `0x05`.
The other three count bytes are not yet pinned.

**Sections 0 and 2 are one continuous ascending `u16` index.** s0's last value sits just below
s2's first in every file (game 7408 -> 7421, ipod 11559 -> 11566, world 37957 -> 37965), with s5
and s6 holding single `u32`s just past s2's end. s0 is zero-*padded*, not strictly monotonic --
world's apparent disorder was one trailing `0`.

**The index addresses section 1 in `u16` units, and section 1 is variable-length records.** At
`idx*2` the slices are clean, and their length histogram is 10 and 12 bytes dominant (485/684 in
game, 2023 in ipod, 5667 in world), 8 a minority, plus rare outliers -- one **478-byte** record
in world, 70 and 58 in game. That is why no fixed stride scored well in a periodicity test.
Consecutive records carry counters incrementing by exactly 1.

Section 1 is **not** fully covered by the index: game's last index reaches `0x3B46`, leaving
11,986 bytes beyond it (18,764 in ipod, 63,548 in world) of the same kind of data -- the `84 01
... 00 40` signature recurs there identically.

**A reading that does NOT hold: MIDI.** The recurring `84 01`, `02 90`, `00 40`, `7f` values
invite it, but a census of the leading byte across all ~1,225/2,119/5,878 records shows no
status-byte alphabet in `0x80`-`0xEF`. It is dominated by small values -- game `0`(745),
`1`(173), `2`(108), `4`(82); world spreading `0`-`12` with hundreds each -- so the leading `u16`
is a value (position or delta), not an opcode. Recorded because the MIDI reading is exactly the
kind of coherent story this file has three times had to retract.

### The decrypted image, dumped — and the magic is genuinely absent

The image was dumped out of a running recomp under gdb and searched directly, which upgrades the
paragraph below from "cannot be searched" to a measurement. Recipe in
`probe/harness/dump_image.gdb`: `ptrace_scope` is 1 here so gdb must be the **parent** (which
`run_session.sh`'s `GDB_SCRIPT=` arranges), break on `sub_82EE7828` (the second guest function of
a boot, so memory is mapped), read the membase from **`$rsi`** rather than assuming it — every
lifted function is `void sub_X(PPCContext&, uint8_t* base)`, so `base` is in `rsi` under SysV,
and it measured `0x100000000` — then `dump binary memory` in 2 MB chunks, because reserved guest
pages are `PROT_NONE` and gdb fails a command where an in-process `memcpy` would fault the game.
Absolute paths throughout: `run_session.sh` `cd`s into `$OUT` first.

Validated before trusting any negative: the first chunk contains
`"!This program cannot be run in DOS mode."`, `EAWebKit/TransportHandlerDirtySDK` and
`EAText/FontFusion`. The populated range runs to about `0x83200000` (the `0x83200000` chunk is 98%
zeros).

**`"PFDx"` is absent from the decrypted image.** The filenames are not: the loader knows these
files by name and validates them by **checksum**, which its own diagnostic states outright —

```
0x8216C178  "PATHI_verifymusfile - file %s (checksum 0x%X does not match .mpf data (checksum 0x%X)."
```

That independently confirms section 7's role (it carries the companion `.mus` content hash) from
the game's side rather than from file structure, and it names a module prefix, `PATHI_`, worth
harvesting for the rest of the music API.

| string | guest address | `lis` / low half |
|---|---|---|
| `dataudio/music/game.mpf` | `0x83043334` | `-31996` / `0x3334` |
| `dataudio/music/ipod.mpf` | `0x83043350` | `-31996` / `0x3350` |
| `dataudio/music/world.mpf` | `0x8304336C` | `-31996` / `0x336C` |
| `dataudio/music/{Game,World,Ipod}_Stream.mus` | `0x8224E610` / `E634` / `E658` | `-32220` / `0xE610`… |
| `'%.*s%d.mus'` | `0x8216A8C0` | `-32234` / `0xA8C0` |
| `'%d_dlc_ambience.sns'` | `0x8224A2D0` | `-32220` / `0xA2D0` |

**Next step:** find the lifted code referencing those `.mpf` path addresses. That is the reader,
and it is the route into sections 0-3 — which byte-pattern inference should not be asked to
supply, given this document has already had to retract three readings reached that way.

**Why the parser could not be read instead.** The magic is not greppable anywhere: zero hits for
`"PFDx"` or `"PFD"` in `default.xex`, either `default.xexp`, or `EAWebkit.xex`, and zero for the
`0x50464478` immediate (or its reversed and split forms) across **47,889** lifted functions --
and `generated/` does lift the whole executable, not just the audio corpus, so that absence is
evidence rather than a coverage gap. The reason is that `default.xex` is a **XEX2** image whose
`.rdata` is compressed, so no string search from outside can succeed. Finding the parser needs
the decrypted image, which the recomp necessarily holds in memory at `virtual_membase +
0x82000000`.

### Not attempted

Sequencing semantics -- how sections 0 through 3 drive transitions between segments -- is
untouched. Converting interactive music means emitting segments *plus* a usable map, and
the map's meaning is the open half.
