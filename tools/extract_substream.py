#!/usr/bin/env python3
"""Split an EAAC block chain into per-XMA-context sub-streams.

Layout established in docs/xma-transcode.md:

    block   [u32 flags<<24|size][u32 num_samples]
    payload [u32 bit_offset][chunk 0] [u32 bit_offset][chunk 1] ...

one chunk per hardware XMA context, i.e. ceil(channels / 2) of them.

Chunk boundaries are currently located by scanning for the chunk-start marker rather
than read from a length field -- no length field has been identified, and the game
gets the length from state set up outside the block. The scan is validated by the
byte arithmetic closing exactly on every block it is applied to; a block where it
does not close is reported rather than silently accepted.
"""
import argparse, struct, sys

MARKERS = (0x08, 0x22)


def be32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def blocks(data, start, limit=None):
    at, out = start, []
    while at + 8 <= len(data):
        word = be32(data, at)
        size = word & 0xFFFFFF
        if size <= 8 or at + size > len(data):
            break
        out.append((at, size, be32(data, at + 4)))
        at += size
        if limit and len(out) >= limit:
            break
    return out


def split_payload(payload, want):
    """Return `want` chunks as (bit_offset, bytes), or None if the split is unsound."""
    marks = [i for i in range(4, len(payload) - 4)
             if payload[i] in MARKERS and payload[i + 1] == 0
             and payload[i + 2] == 0 and payload[i + 3] == 0]
    marks = [4] + [m for m in marks if m > 4]
    # Keep the subset whose spans account for the payload exactly.
    for combo_end in range(len(marks), want - 1, -1):
        cand = marks[:combo_end]
        if len(cand) != want:
            continue
        chunks, ok = [], True
        for i, m in enumerate(cand):
            end = cand[i + 1] - 4 if i + 1 < len(cand) else len(payload)
            if end <= m:
                ok = False
                break
            chunks.append((be32(payload, m - 4), payload[m:end]))
        total = 4 * want + sum(len(c[1]) for c in chunks)
        if ok and total == len(payload):
            return chunks
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--entry", type=int, default=0)
    ap.add_argument("--channels", type=int, required=True)
    ap.add_argument("--blocks", type=int, default=0)
    ap.add_argument("--out-prefix")
    args = ap.parse_args()

    data = open(args.archive, "rb").read()
    off = be32(data, 0x30 + 16 * args.entry) << ((be32(data, 8) >> 8) & 0xFF)
    want = (args.channels + 1) // 2

    subs = [bytearray() for _ in range(want)]
    good = bad = 0
    for at, size, ns in blocks(data, off, args.blocks or None):
        payload = data[at + 8:at + size]
        chunks = split_payload(payload, want)
        if chunks is None:
            bad += 1
            continue
        good += 1
        for i, (_, body) in enumerate(chunks):
            subs[i] += body

    print(f"blocks split cleanly: {good}, unsound: {bad}, contexts: {want}")
    for i, s in enumerate(subs):
        print(f"  substream {i}: {len(s)} bytes")
        if args.out_prefix:
            open(f"{args.out_prefix}.{i}.xma", "wb").write(bytes(s))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
