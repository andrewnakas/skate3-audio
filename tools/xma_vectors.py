#!/usr/bin/env python3
"""Build per-chunk XMA2 decode vectors from a real archive, for checking a Rust decoder.

Each vector is one chunk of one context: the raw XMA2 bytes, and the PCM the ffmpeg CLI
produces for that chunk *on its own*. A decoder restarted per chunk must reproduce those
bytes exactly, which is a check that needs no libavcodec headers -- only the ffmpeg binary.

What this deliberately does NOT check is the state carried between chunks. Per
docs/xma-transcode.md, an independently decoded mid-stream chunk is short by exactly 64
samples of MDCT overlap, and reproducing the hardware means keeping that state. So these
vectors pin the frame decoder, and the overlap is verified separately by the sample counts
the block headers declare -- both halves are needed, and neither substitutes for the other.

  xma_vectors.py ARCHIVE OUTDIR --channels 5 [--rate 48000] [--entry 0] [--blocks 8]

Writes OUTDIR/manifest.json plus cNN_bMM.xma / cNN_bMM.pcm per chunk.
"""
import argparse, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib
eaac = importlib.import_module("eaac_decode")
wrap = importlib.import_module("wrap_xma")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("outdir")
    ap.add_argument("--channels", type=int, required=True)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--entry", type=int, default=0)
    ap.add_argument("--blocks", type=int, default=8)
    a = ap.parse_args()

    data = open(a.archive, "rb").read()
    off, _ = eaac.archive_entry(data, a.entry)
    want = (a.channels + 1) // 2
    widths = [2] * (a.channels // 2) + ([1] if a.channels % 2 else [])
    os.makedirs(a.outdir, exist_ok=True)

    records, at, blk, unsound = [], off, 0, 0
    while at + 8 <= len(data) and (not a.blocks or blk < a.blocks):
        size = eaac.be32(data, at) & 0xFFFFFF
        if size <= 8 or at + size > len(data):
            break
        samples = eaac.be32(data, at + 4)
        spans = eaac.split_payload(data[at + 8:at + size], want)
        if spans is None:
            unsound += 1
        else:
            for ctx, raw in enumerate(spans):
                base = os.path.join(a.outdir, f"c{ctx:02d}_b{blk:03d}")
                open(base + ".xma", "wb").write(raw)
                with tempfile.TemporaryDirectory() as work:
                    riff = os.path.join(work, "w.wav")
                    # block_align = the whole chunk: one chunk is one independently framed
                    # unit, and a uniform 2048 desyncs after ~23 KB (docs/xma-transcode.md).
                    open(riff, "wb").write(
                        wrap.build(raw, widths[ctx], a.rate, samples, len(raw)))
                    pcm = subprocess.run(
                        ["ffmpeg", "-v", "error", "-i", riff, "-f", "s16le", "-"],
                        capture_output=True).stdout
                open(base + ".pcm", "wb").write(pcm)
                records.append({"context": ctx, "block": blk, "channels": widths[ctx],
                                "rate": a.rate, "declared_samples": samples,
                                "xma_bytes": len(raw), "pcm_samples": len(pcm) // 2 // widths[ctx],
                                "stem": os.path.basename(base)})
        blk += 1
        at += size

    manifest = {"archive": os.path.basename(a.archive), "entry": a.entry,
                "channels": a.channels, "rate": a.rate, "contexts": want,
                "widths": widths, "blocks": blk, "unsound_splits": unsound,
                "chunks": records}
    json.dump(manifest, open(os.path.join(a.outdir, "manifest.json"), "w"), indent=1)
    short = sum(1 for r in records if r["pcm_samples"] != r["declared_samples"])
    print(f"{len(records)} chunk vectors, {blk} blocks, {unsound} unsound splits")
    print(f"{short} of {len(records)} decoded short of the declared count "
          f"(expected: every chunk after the stream's first loses 64 samples of overlap)")
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
