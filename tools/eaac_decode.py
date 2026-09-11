#!/usr/bin/env python3
"""Decode an EAAC (codec 3 / XMA) stream out of a Skate 3 archive into WAV.

Implements the recipe validated in docs/xma-transcode.md:

  1. walk the block chain            {flags<<24|size, num_samples}
  2. split each payload into         ceil(channels / 2) chunks
  3. decode EACH CHUNK INDEPENDENTLY  (they are separately framed -- concatenating
                                       first and decoding once desyncs)
  4. append PCM per context, then interleave the contexts

Chunk lengths are located by scanning for the start marker; no length field has been
identified. The scan is self-checking: a block whose spans do not account for its
payload exactly is reported rather than silently accepted.

Needs ffmpeg with the xma2 decoder.
"""
import argparse, itertools, os, struct, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wrap_xma import build as build_riff

MARKERS = (0x08, 0x22)


def be32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def archive_entry(data, index):
    shift = (be32(data, 8) >> 8) & 0xFF
    at = 0x30 + 16 * index
    return be32(data, at) << shift, be32(data, at + 8)


def split_payload(payload, want):
    """Split a block payload into its per-context chunks using the length field.

    Each chunk is preceded by a u32 from which its length follows exactly:

        length = (field - 19) / 4

    Verified on 60 consecutive ambience blocks, every one accounting for its payload
    to the byte. The music container uses the same relation with a constant of 18
    against the block body, so the encoding is shared and only the bias differs.

    This replaces an earlier marker scan that guessed chunk starts and then
    disambiguated by decoding every candidate. That worked but was slow, depended on
    an empirical set of marker bytes, and could not tell two balancing splits apart
    without decoding them. The length field makes the split deterministic.
    """
    chunks, pos = [], 0
    for _ in range(want):
        if pos + 4 > len(payload):
            return None
        field = struct.unpack_from(">I", payload, pos)[0]
        if (field - 19) % 4:
            return None
        length = (field - 19) // 4
        if length <= 0 or pos + 4 + length > len(payload):
            return None
        chunks.append(payload[pos + 4:pos + 4 + length])
        pos += 4 + length
    return chunks if pos == len(payload) else None


def decode_chunk(raw, channels, rate, samples, workdir, tag):
    wav = os.path.join(workdir, f"{tag}.wav")
    pcm = os.path.join(workdir, f"{tag}.pcm")
    with open(wav, "wb") as fh:
        fh.write(build_riff(raw, channels, rate, samples, len(raw)))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-i", wav,
                        "-f", "s16le", "-y", pcm],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(pcm):
        return None, r.stderr.strip()
    with open(pcm, "rb") as fh:
        return fh.read(), r.stderr.strip()


def write_wav(path, channels, rate, frames):
    data = b"".join(struct.pack("<" + "h" * channels, *f) for f in frames)
    fmt = struct.pack("<HHIIHH", 1, channels, rate,
                      rate * channels * 2, channels * 2, 16)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("out")
    ap.add_argument("--entry", type=int, default=0)
    ap.add_argument("--channels", type=int, required=True)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--blocks", type=int, default=0)
    ap.add_argument("--dump-chunks", metavar="PREFIX",
                    help="write per-context XCHK containers for tools/xma_decode.c "
                         "instead of decoding here; that path keeps one decoder alive "
                         "across chunks and so avoids the 64-sample priming loss")
    args = ap.parse_args()

    data = open(args.archive, "rb").read()
    off, _ = archive_entry(data, args.entry)
    want = (args.channels + 1) // 2
    # 5 channels -> 2 + 2 + 1; the last context carries the remainder.
    widths = [2] * (args.channels // 2) + ([1] if args.channels % 2 else [])

    ctx_pcm = [bytearray() for _ in range(want)]
    ctx_chunks = [[] for _ in range(want)]
    at, nblk, declared, unsound = off, 0, 0, 0
    with tempfile.TemporaryDirectory() as work:
        while at + 8 <= len(data):
            size = be32(data, at) & 0xFFFFFF
            if size <= 8 or at + size > len(data):
                break
            samples = be32(data, at + 4)
            spans = split_payload(data[at + 8:at + size], want)
            if spans is None:
                unsound += 1
            else:
                declared += samples
                for i, raw in enumerate(spans):
                    ctx_chunks[i].append(raw)
                    if not args.dump_chunks:
                        pcm, err = decode_chunk(raw, widths[i], args.rate, samples,
                                                work, f"b{nblk}c{i}")
                        if pcm is None:
                            print(f"  block {nblk} ctx {i}: decode failed: {err}")
                        else:
                            ctx_pcm[i] += pcm
            nblk += 1
            at += size
            if args.blocks and nblk >= args.blocks:
                break

    if args.dump_chunks:
        for i, spans in enumerate(ctx_chunks):
            path = f"{args.dump_chunks}.{i}.xchk"
            with open(path, "wb") as fh:
                fh.write(b"XCHK")
                fh.write(struct.pack("<III", widths[i], args.rate, len(spans)))
                for raw in spans:
                    fh.write(struct.pack("<I", len(raw)))
                    fh.write(raw)
            print(f"  wrote {path}: {len(spans)} chunks, {widths[i]}ch, "
                  f"{sum(len(r) for r in spans)} bytes")
        print(f"declared samples: {declared}")
        return 0

    per = [len(p) // (2 * widths[i]) for i, p in enumerate(ctx_pcm)]
    print(f"blocks: {nblk} (unsound splits: {unsound})")
    print(f"declared samples: {declared}")
    print(f"decoded per context: {per}")
    if not per or min(per) == 0:
        return 1

    n = min(per)
    frames = []
    for s in range(n):
        row = []
        for i, w in enumerate(widths):
            base = (s * w) * 2
            row.extend(struct.unpack_from("<" + "h" * w, ctx_pcm[i], base))
        frames.append(row)
    write_wav(args.out, args.channels, args.rate, frames)
    print(f"wrote {args.out}: {n} frames x {args.channels}ch "
          f"({n / args.rate:.2f}s)  match={'YES' if n == declared else 'NO'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
