# The `rw::audio` command queue — decompiled

Source: Ghidra decompilation of `sub_82B28A00` from the TU3 image, cross-checked against
the PPC listing quoted in `skate3recomp-dev/src/skate3_audio_fixes.cpp`.

## Confirmation of the existing analysis

The decompiler independently reproduces every offset the recomp had inferred from crash
dumps: `Player+8` is the `System*`, the queue buffer is at `System+0x30` (48), the write
offset at `System+0xCC` (204), and the offset is published *before* the record is stored.

```c
puVar1 = (undefined4 *)(*(int *)(iVar3 + 0x30) + *(int *)(iVar3 + 0xcc));
*(int *)(iVar3 + 0xcc) = *(int *)(iVar3 + 0xcc) + 0x14;   // publish first
*puVar1    = sub_82B28B78;                                 // then the handler
puVar1[1]  = param_1;                                      // then the object
puVar1[2]  = *(undefined4 *)(param_3 + 4);                 // then the payload
```

So the race is exactly as documented, and `sub_82B28B78` is confirmed as a command
*handler* stored as the record's first word. Record layout is
`{handler_fn, object, payload…}`.

## Correction: records are variable length, not 20 bytes

The existing notes describe "a 20-byte command record". `sub_82B28A00` actually emits
three different sizes, selected by its second argument:

| `param_2` | record size | handler |
|---|---|---|
| 0 | 0x14 (20) | `sub_82B28B78` |
| 1 | 0x08 (8)  | `0x82B28C18` |
| 2 | 0x0C (12) | `0x82B28CC0` |

Two previously unknown handlers fall out of this: **`0x82B28C18`** and **`0x82B28CC0`**.

**This makes the race worse than the existing write-up assumes.** A consumer that observes
the advanced write offset before the stores land does not merely read a stale payload — it
cannot know how long the record is, because the length is implied by the handler, and the
handler is one of the words written *after* the offset is published. A torn read therefore
desynchronises the whole queue from that point on, not just one record. That is consistent
with the observed failure mode of a lookup that "misses forever" rather than recovering on
the next frame.

It also means a fix must publish the size atomically with, or before, the handler — simply
ordering the stores with a release fence is necessary but the record length still has to be
recoverable by the consumer before it trusts the handler.

## The fourth path is not an append

When `param_2` is anything other than 0, 1 or 2, the function does not touch the queue at
all. It searches two structures on the player object and then writes a sentinel:

- a linked list walked from `Player+0x148` through `next` at `+0xC`
- a 20-element array at `Player+0x54`, stride 12, with a discriminator byte at `+0x5D`

and on either outcome stores `0x7FF7FFF1` into `param_3+8` plus a constant into
`param_3+0xC`. `0x7FF7FFF1` is a NaN payload, so this looks like "mark this voice/param
invalid" rather than a command at all. The two constants are read from `.rdata`
(`0x82165A10`, `0x8231A844`).

This branch is worth reading properly before anyone wraps `sub_82B28A00` in a lock on the
assumption that it is purely a queue producer — for three of its four paths it is, but the
fourth mutates caller-owned state instead.

## Status

~~`sub_82B28B78`, `0x82B28C18` and `0x82B28CC0` are the next functions to read~~ — **done,
2026-09-11.** All three consumers are read and ported natively, and the record layouts this
document predicts from the producer were confirmed independently from each consumer's own body:
20 bytes with `player` at `+4` then three floats for `EVENT_PLAY`, 8 bytes for `EVENT_STOP`,
12 bytes with the packet at `+8` for `EVENT_SUBMIT`. The producer's `lis`/`addi` handler
derivation is now `static_assert`ed against those three addresses in
`skate3_audio_native.cpp`, so a misread fails the build.

Verification status, from `docs/shadow-harness.md`: the producer `sub_82B28A00` is clean over
6,706 comparable calls, `EVENT_SUBMIT` is promoted, `EVENT_PLAY` is clean at a single input
point, and `EVENT_STOP` has **no comparable path** — it arrives with a live decoder, whose
release the harness cannot rewind.

**The ordering fix in this document is deliberately not landed.** Publishing the write offset
before the handler is the race, and reproducing it exactly is what makes the producer
comparable at all — a fix would diverge from the original by construction, and the harness
cannot tell an intended behaviour change from a porting mistake. It lands as its own change
against the now-verified body. Note also that this document specifies what a fix must *achieve*
(publish the size atomically with or before the handler) but not an implementation; the record
length still has to be recoverable by the consumer before it trusts the handler, and nothing
here says how.

## The wire format, decompiled

The three handlers `sub_82B28A00` dispatches to are the `PacketPlayer` events the image's
own metadata documents. Reading them settles both the record layout and the player state.

| handler | size | event |
|---|---|---|
| `sub_82B28B78` | 0x14 | `EVENT_PLAY` |
| `sub_82B28C18` | 0x08 | `EVENT_STOP` |
| `sub_82B28CC0` | 0x0C | `EVENT_SUBMIT` |

**Handlers return their own record size.** `sub_82B28CC0` ends `return 0xc;` — the same
0xC that `sub_82B28A00` advanced the write offset by. So the drain learns how far to
advance from the handler's return value, not from the record.

That closes the question raised above, and confirms the severity: the length is knowable
only *after* calling through the handler pointer, and the handler pointer is stored after
the offset is published. A torn read therefore calls a garbage pointer **and** advances by
a garbage amount, desynchronising every subsequent record. Recovery is impossible without
resetting the queue, which is exactly the "misses forever" behaviour observed.

### `EVENT_PLAY` — `sub_82B28B78`

Unpacks three `PlayParam`s from the record and lands them on the player. The metadata
declares them in the order `PLAYPARAM_FORMAT`, `PLAYPARAM_SAMPLERATE`,
`PLAYPARAM_NUMCHANNELS`, which matches the stores:

| record | player | meaning |
|---|---|---|
| +0x08 | +0x160 (352) | format index — indexes the `P6L0`/`PFN0` tag table |
| +0x0C | +0x154 (340) | sample rate |
| +0x10 | +0x15F (351) | channel count |

All three arrive as **floats** and the two byte fields are truncated via a
float→int64→int8 conversion. This **independently confirms** the offsets
`skate3_audio_fixes.cpp` inferred from crash dumps (`kPlayerRate` 340,
`kPlayerChannels` 351, `kPlayerFormat` 352, `kPlayerSource` 80) — they are correct.

It then writes the channel count into the source object at `Player+0x50`, and calls the
codec lookup `sub_82B29018` — but only when the state byte is neither 4 nor 0.

### New player fields

| offset | meaning |
|---|---|
| +0x148 / +0x14C | submitted-packet FIFO, head and tail |
| packet +0x0C | `next` pointer in that FIFO |
| +0x150 | active decoder/voice handle (0 when idle) |
| +0x158 | set to 0xFF when playback is torn down |
| +0x15E | **state byte** — 1 = playing (set by PLAY), 4 = stopped (set by STOP) |

`sub_82B3C930` is the decoder teardown, called from `EVENT_STOP`.

### `EVENT_STOP` and `EVENT_SUBMIT`

`EVENT_STOP` tears down the decoder if one is live, zeroes 0x14 bytes of play state from
+0x150, sets the state byte to 4, and walks the FIFO unlinking every packet — matching the
documented "stop all playback and remove all submitted packets from the internal queue".

`EVENT_SUBMIT` is a plain singly-linked-list append onto that FIFO, which is the
documented "queues up the submitted packets and plays them in FIFO sequence".

### Why the state guard matters

`EVENT_PLAY` only performs the codec lookup when the state byte is neither 4 nor 0. So a
`PLAY` arriving while the player is stopped, or freshly zeroed, silently skips the lookup.
Any fix to the queue race has to preserve that guard — it is not dead code, it is what
keeps a `PLAY` racing a `STOP` from building a decoder for a player that is going away.

## The consumer — located, and bug 1 fully characterised

The consumer is inside `sub_82B48530` (the System tick), in its final locked phase. In
essence:

```c
base = *(void **)(System + 0x30);                  // ring buffer
end  = base + *(int *)(System + 0xCC);             // snapshot the write offset ONCE
for (p = base; p < end; p += size)
    size = (*(code *)*p)(p);                       // call record[0], it returns its length
if (System->0xD0 < System->0xCC) System->0xD0 = System->0xCC;   // high-water mark
System->0xCC = 0;                                  // reset the ring
System->0x100++;                                   // drain counter
```

This confirms, from the consumer side, everything inferred earlier from the handlers: the
record's first word **is** the handler pointer, the handler **returns its own record
length**, and the loop advances by that return value.

### New System fields

| offset | meaning |
|---|---|
| +0x30 | command ring buffer base |
| +0xCC | write offset (bytes used this frame; reset to 0 each drain) |
| +0xD0 | high-water mark of ring usage |
| +0xE8 | elapsed time of the command-execution phase |
| +0xF4 | accumulated time of the earlier phases |
| +0x100 | drain counter |

The ring is **frame-scoped**: it is filled during the frame and fully consumed and reset by
the drain, rather than being a circular buffer with independent read and write cursors.

### Exactly how the race kills it

`end` is snapshotted once, under the lock. A producer that appends *after* that snapshot is
simply picked up next frame — harmless. The lethal interleaving is the other one:

1. An unlocked producer advances `+0xCC` **before** storing the record.
2. The drain snapshots `end` and includes that record.
3. The record's first word has not been stored yet, so `*p` is stale heap data.
4. `(*(code *)*p)(p)` calls through it — this is the reported
   `Call to invalid or unregistered function at guest address 0xFFFDFFFF`.
5. Worse, `size` is then also garbage, so `p` advances by a garbage amount and the loop
   walks arbitrary memory for the remainder of the drain.

So a single torn append corrupts the whole rest of the frame's command stream, not one
record — which matches the observed "misses forever" behaviour far better than a single bad
record would.

### Why the current mitigation is incomplete

The mitigation in `skate3_audio_fixes.cpp` wraps the five unlocked producers in a
**non-blocking** try-lock, and its own comment is explicit that on failure "the append
proceeds exactly as it does today". So under contention — precisely when the race is most
likely — it silently falls back to the racy path.

The ordering is what actually matters, and it needs no lock at all. The producers must
store the record first and publish the offset second, with a release barrier between; the
drain must read the offset with an acquire barrier. Then a reader that sees the advanced
offset is guaranteed to see the record behind it. The original code has the two stores in
the wrong order, and on in-order Xenon that was survivable; correcting the order (rather
than serialising with a lock that may not be taken) fixes it unconditionally and costs
nothing on the hot path.

Note the guest is doing a non-atomic read-modify-write on `+0xCC`, so concurrent producers
can still lose appends to each other. Making `+0xCC` an atomic fetch-add, plus the release
ordering above, addresses both without a lock.
