# The `.grain` banks — a lead, not a format

`grains.big` is the archive most likely to hold the sounds skating actually makes. It parses as a
normal EB v3 archive with **14 members**, all `.grain`, and nothing in this project decodes them.
This file records what one pass over the raw bytes shows, so the next person starts from evidence
rather than from scratch. **Nothing here is established.** No claim below has been checked against
a second source, and the project's own rule is that a coherent story is the most dangerous kind.

## What the bytes show

Every one of the 14 members begins with the same shape:

```
u32   0x00000070 .. 0x000000b0     small, varies per member, looks like a size or a count
u32   0x4142xxxx .. 0x41afxxxx     reads as a float in the 12-22 range
u32   0x00100180                   identical in all 14
u32   0x00000018                   identical in all 14
```

Member sizes run from 123 KB to 284 KB, which is the right order for a set of short grain samples
rather than for a metadata table.

## What that suggests, and what would test it

The float-looking word is the interesting one: values cluster between roughly 12 and 22, and the
member with the smallest first word (`0x70`) also has the smallest float (`0x41426f5c`, about
12.1). If that word is a duration in seconds, the smallest member should be the shortest sound,
and the ordering of the 14 floats should match the ordering of their audio lengths. That is a
prediction over the whole set, which is the kind of test this project trusts; a match on two or
three members proves nothing, and the failure mode of reading a field as a duration from its first
few records has already happened once here, to a `.mpf` field.

Two constants, `0x00100180` and `0x00000018`, are identical across all 14 and so carry no
per-member information. `0x18` is 24, a plausible record size or header length.

## What is not known

Whether a `.grain` holds audio at all, or only references into another archive; whether the grains
are EA Audio Core streams like everything else on this disc; how a grain is selected at run time.
`audiofiles.big` holds 376 `.abk`, 20 `.bnk`, 9 `.csi` and 23 `.ems` members, and the mapping from
a game event to a sound almost certainly lives in those rather than here.

## Why it matters

The Rust engine can decode and play any stream it is pointed at, and it can pick an ambience bed
by name. What it cannot do is make a sound when the board hits the ground, because nothing maps an
event to a sound. These banks and the `.abk` files are where that mapping lives.
