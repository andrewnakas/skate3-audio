#!/usr/bin/env python3
"""Compare two guest-mixer captures for exactness.

`audio_dump_path` taps every guest mixer submit before the 5.1->stereo fold: 256 frames
x 6 channels of big-endian float32, **planar**, 6144 bytes per submit. That tap is the
reference a native or Rust reimplementation has to match.

"Exact" here means bit-identical float32, not "sounds the same". This reports the first
divergence precisely, because a reimplementation that drifts after N submits is a
different problem from one that is wrong immediately.
"""
import argparse, struct, sys

FRAMES = 256
CHANNELS = 6
SUBMIT = FRAMES * CHANNELS * 4


def submits(path):
    with open(path, "rb") as fh:
        while True:
            block = fh.read(SUBMIT)
            if len(block) < SUBMIT:
                return
            yield block


def planar(block):
    """Return per-channel float lists from one planar submit."""
    vals = struct.unpack(f">{FRAMES * CHANNELS}f", block)
    return [vals[c * FRAMES:(c + 1) * FRAMES] for c in range(CHANNELS)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference")
    ap.add_argument("candidate")
    ap.add_argument("--tolerance", type=float, default=0.0,
                    help="max absolute difference to accept; 0 means bit-identical")
    args = ap.parse_args()

    ref, cand = submits(args.reference), submits(args.candidate)
    n = 0
    worst = 0.0
    first_bad = None
    while True:
        a, b = next(ref, None), next(cand, None)
        if a is None or b is None:
            break
        if a != b:
            pa, pb = planar(a), planar(b)
            for c in range(CHANNELS):
                for i in range(FRAMES):
                    d = abs(pa[c][i] - pb[c][i])
                    if d > worst:
                        worst = d
                    if d > args.tolerance and first_bad is None:
                        first_bad = (n, c, i, pa[c][i], pb[c][i])
        n += 1

    extra_ref = sum(1 for _ in ref)
    extra_cand = sum(1 for _ in cand)
    print(f"compared {n} submits ({n * FRAMES} frames, {n * FRAMES / 48000:.2f}s)")
    if extra_ref or extra_cand:
        print(f"  length mismatch: reference has {extra_ref} extra, candidate {extra_cand}")
    if first_bad is None:
        print(f"  EXACT{'' if args.tolerance == 0 else f' within {args.tolerance}'}"
              f"  (largest difference seen {worst:g})")
        return 0
    s, c, i, x, y = first_bad
    print(f"  DIVERGES at submit {s}, channel {c}, frame {i}: {x!r} vs {y!r}")
    print(f"  that is {(s * FRAMES + i) / 48000:.3f}s in; largest difference {worst:g}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
