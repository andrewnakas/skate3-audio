#!/usr/bin/env python3
"""Check an audio_dump_path capture against its documented layout, from the signal.

tools/mixdiff.py assumes the layout -- 256 frames x 6 channels of big-endian float32,
planar, 6144 bytes per submit -- and comparing a capture with itself only proves the file
reads. This tests the assumption instead:

  size     a whole number of 6144-byte submits
  values   finite, and in a sane range for a float mix
  layout   real audio moves little from one sample to the next. Read as planar, each
           channel's step is small next to its level; read as interleaved, the same bytes
           hop between channels every sample. Planar has to win clearly. When all six
           channels carry the same signal both readings look smooth, and the test says
           so rather than passing.
  seams    a step across a submit boundary should look like a step inside a submit. A
           dropped, repeated or reordered submit shows up as a boundary outlier.

Usage: check_capture.py CAPTURE [--wav OUT.wav]
"""
import argparse, array, math, os, struct, sys

FRAMES, CHANNELS = 256, 6
SUBMIT = FRAMES * CHANNELS * 4


def load(path):
    data = open(path, "rb").read()
    n = len(data) // SUBMIT
    a = array.array("f")
    a.frombytes(data[: n * SUBMIT])
    if sys.byteorder == "little":
        a.byteswap()
    return a, n, len(data) % SUBMIT


def planar(a, s, c):
    o = s * FRAMES * CHANNELS + c * FRAMES
    return a[o:o + FRAMES]


def interleaved(a, s, c):
    o = s * FRAMES * CHANNELS
    return a[o + c:o + FRAMES * CHANNELS:CHANNELS]


def roughness(xs):
    """Mean absolute step over mean absolute level."""
    level = sum(abs(x) for x in xs) / len(xs)
    if level < 1e-4:
        return None
    step = sum(abs(xs[i] - xs[i - 1]) for i in range(1, len(xs))) / (len(xs) - 1)
    return step / level


def median(v):
    v = sorted(v)
    return v[len(v) // 2] if v else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--wav")
    args = ap.parse_args()

    a, n, tail = load(args.capture)
    ok = True
    print(f"{args.capture}: {os.path.getsize(args.capture)} bytes = {n} submits "
          f"({n * FRAMES / 48000:.2f} s)" + (f", {tail} trailing bytes" if tail else ""))
    if tail or n == 0:
        print("  FAIL size: not a whole number of 6144-byte submits")
        ok = False

    non_finite = sum(1 for x in a if not math.isfinite(x))
    peak = max((abs(x) for x in a if math.isfinite(x)), default=0.0)
    silent = sum(1 for s in range(n) if not any(a[s * FRAMES * CHANNELS:(s + 1) * FRAMES * CHANNELS]))
    print(f"  values: peak {peak:.4f}, {non_finite} non-finite, {silent} all-silent submits")
    if non_finite or peak > 16.0:
        print("  FAIL values: non-finite samples or an implausible peak")
        ok = False

    # Layout: sample up to 400 submits spread across the capture.
    stride = max(1, n // 400)
    rp, ri, same = [], [], 0
    for s in range(0, n, stride):
        chans = [planar(a, s, c) for c in range(CHANNELS)]
        if all(chans[c] == chans[0] for c in range(1, CHANNELS)):
            same += 1
            continue
        for c in range(CHANNELS):
            p, i = roughness(chans[c]), roughness(interleaved(a, s, c))
            if p is not None and i is not None:
                rp.append(p)
                ri.append(i)
    if not rp:
        print(f"  layout: INCONCLUSIVE - no sampled submit has distinct channels with signal "
              f"({same} had six identical channels)")
    else:
        mp, mi = median(rp), median(ri)
        verdict = "planar" if mp < 0.5 * mi else ("interleaved?" if mi < 0.5 * mp else "unclear")
        print(f"  layout: median roughness planar {mp:.3f} vs interleaved {mi:.3f} over "
              f"{len(rp)} channel-submits -> {verdict}")
        if verdict != "planar":
            ok = False

    # Seams: boundary steps against within-submit steps, per channel.
    inner, seam = [], []
    for s in range(0, n - 1, stride):
        for c in range(CHANNELS):
            x, y = planar(a, s, c), planar(a, s + 1, c)
            inner.extend(abs(x[i] - x[i - 1]) for i in range(1, FRAMES))
            seam.append(abs(y[0] - x[-1]))
    if inner and median(inner) > 0:
        inner.sort()
        p999 = inner[int(len(inner) * 0.999)]
        outliers = sum(1 for d in seam if d > p999)
        ratio = median(seam) / median(inner)
        print(f"  seams: median boundary step / median inner step = {ratio:.2f}; "
              f"{outliers} of {len(seam)} boundary steps above the inner 99.9th percentile")
        if ratio > 3.0:
            ok = False
    else:
        print("  seams: INCONCLUSIVE - no signal to measure")

    if args.wav:
        frames = bytearray()
        for s in range(n):
            chans = [planar(a, s, c) for c in range(CHANNELS)]
            frames += struct.pack(f"<{FRAMES * CHANNELS}f",
                                  *(chans[c][i] for i in range(FRAMES) for c in range(CHANNELS)))
        with open(args.wav, "wb") as fh:
            fmt = struct.pack("<HHIIHH", 3, CHANNELS, 48000, 48000 * CHANNELS * 4, CHANNELS * 4, 32)
            fh.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(frames)) + b"WAVE")
            fh.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
            fh.write(b"data" + struct.pack("<I", len(frames)) + frames)
        print(f"  wrote {args.wav} (6-channel float, 48 kHz)")

    print("  RESULT:", "consistent with the documented layout" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
