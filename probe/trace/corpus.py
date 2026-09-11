#!/usr/bin/env python3
"""Rebuild the audio corpus from RexGlue's lifted sources.

The 1,694-function list from docs/decompilation-status.md lived in out/audio_funcs.txt and
was never committed. This reconstructs it without Ghidra:

  seed    every function in the audio window 0x82B00000-0x82B87000, plus the three audio
          functions docs/rw-audio-core.md shows sit outside it
  closure one round over direct guest calls (`sub_X(ctx, base)` in the lifted form)

Measured on the Linux tree, 2026-09-11: the seed reproduces the documented 1,536 exactly;
the closure gives 1,693 against 1,694. Resolving `bl`/`b` targets by address instead of by
lowered call finds the same 1,693, so the last function is not recoverable from this
tree's generated/ -- most likely a function-boundary difference in the macOS codegen.

Writes {address: {"tu": file, "vec": vector_instruction_count}}.

Usage: corpus.py [--generated DIR] [--out out/corpus.json]
"""
import argparse, collections, glob, json, os, re

LO, HI = 0x82B00000, 0x82B87000
OUT_OF_BAND = ["82671F50", "82D0EBB8", "82D19648"]  # Gain fn1, HwFxReturn fn1, named-object lookup
START = re.compile(r"DEFINE_REX_FUNC\(sub_([0-9A-F]{8})\)")
CALL = re.compile(r"\b(sub_[0-9A-F]{8})\(ctx,\s*base\)")
MNEM = re.compile(r"^\t// ([a-z][a-z0-9_.]*)\s")
VEC_PREFIXES = ("v", "lvx", "stvx", "lvlx", "lvrx", "stvlx", "stvrx", "lvsl", "lvebx", "lvehx",
                "lvewx", "stvebx", "stvehx", "stvewx", "mfvscr", "mtvscr")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated", default="/home/nakas/Documents/skate3/skate3recomp-dev/generated")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "corpus.json"))
    a = ap.parse_args()

    tu, calls, vec = {}, collections.defaultdict(set), collections.Counter()
    cur = None
    for path in sorted(glob.glob(os.path.join(a.generated, "skate3_recomp.*.cpp"))):
        with open(path, errors="ignore") as fh:
            for line in fh:
                m = START.search(line)
                if m:
                    cur = m.group(1)
                    tu[cur] = os.path.basename(path)
                    continue
                if cur is None:
                    continue
                for c in CALL.findall(line):
                    if c[4:] != cur:
                        calls[cur].add(c[4:])
                m = MNEM.match(line)
                if m and m.group(1).startswith(VEC_PREFIXES):
                    vec[cur] += 1

    seed = {x for x in tu if LO <= int(x, 16) < HI} | {x for x in OUT_OF_BAND if x in tu}
    round1 = {c for x in seed for c in calls[x] if c not in seed}
    corpus = seed | round1
    frontier = {c for x in corpus for c in calls[x] if c not in corpus}

    print(f"lifted functions      {len(tu)}")
    print(f"seed                  {len(seed):>5}   documented 1,536")
    print(f"round-1 callees       {len(round1):>5}   documented 158")
    print(f"corpus                {len(corpus):>5}   documented 1,694")
    print(f"residual frontier     {len(frontier):>5}   documented 130; in audio window: "
          f"{sum(LO <= int(x, 16) < HI for x in frontier)} (documented 0)")
    print(f"corpus functions with vector instructions: {sum(1 for x in corpus if vec[x])}, "
          f"{sum(vec[x] for x in corpus)} instructions")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({x: {"tu": tu[x], "vec": vec[x]} for x in sorted(corpus)}, open(a.out, "w"), indent=0)
    print(f"wrote {a.out}")

if __name__ == "__main__":
    main()
