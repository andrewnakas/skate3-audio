#!/usr/bin/env python3
"""Wrap a raw XMA2 sub-stream in a RIFF container ffmpeg can open."""
import argparse, struct, sys


def build(raw, channels, rate, samples, block_align):
    mask = {1: 0x4, 2: 0x3}.get(channels, 0x3)
    blocks = max(1, (len(raw) + block_align - 1) // block_align)
    # XMA2WAVEFORMATEX, 34 bytes, little-endian
    ext = struct.pack("<HIIIIIIIBBH",
                      1,            # NumStreams
                      mask,         # ChannelMask
                      samples,      # SamplesEncoded
                      block_align,  # BytesPerBlock
                      0,            # PlayBegin
                      samples,      # PlayLength
                      0, 0,         # LoopBegin, LoopLength
                      0,            # LoopCount
                      4,            # EncoderVersion
                      blocks)       # BlockCount
    fmt = struct.pack("<HHIIHHH", 0x0166, channels, rate,
                      rate * channels * 2, block_align, 16, len(ext)) + ext
    data = raw + (b"\0" if len(raw) & 1 else b"")
    body = (b"WAVE"
            + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(raw)) + data)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("out")
    ap.add_argument("--channels", type=int, default=2)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--block-align", type=int, default=2048)
    a = ap.parse_args()
    raw = open(a.raw, "rb").read()
    open(a.out, "wb").write(build(raw, a.channels, a.rate,
                                  a.samples or len(raw), a.block_align))
    print(f"wrote {a.out} ({len(raw)} bytes of payload)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
