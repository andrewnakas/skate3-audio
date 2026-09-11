#!/usr/bin/env python3
"""Intersect one or more guest traces with the audio corpus.

In `first` mode each function appears once, tagged with the thread that called it
first, so the thread breakdown is first-caller, not every caller. The count is an upper
bound on what audio work is live: breadth, not frequency.

Usage: analyze_trace.py out/corpus.json TRACE [TRACE...]
"""
import collections, json, os, sys

PHASE2 = {"82B28A00": "cmd queue producer", "82B28B78": "cmd consumer", "82B28C18": "cmd consumer",
          "82B28CC0": "cmd consumer", "82B48530": "cmd queue", "82B48A50": "scheduler tick",
          "82B482F8": "scheduler", "82B48440": "scheduler", "82B7F828": "buffer-pair init",
          "82B7F998": "buffer-pair", "82B7F8A8": "buffer-pair measure"}

def load(path):
    header, first = None, {}
    for line in open(path, errors="replace"):
        if line.startswith("# skate3 guest trace"):
            header = line.strip()
            continue
        if line.startswith("#") or not line.strip():
            continue
        p = line.rstrip("\n").split("\t")
        if len(p) >= 4 and p[3].startswith("sub_") and p[3][4:] not in first:
            first[p[3][4:]] = (int(p[0]), p[2])
    return header, first

def ran(hit, a):
    return f"RAN on {hit[a][1]}" if a in hit else "-- not seen"

def report(corpus, name, first):
    hit = {a: v for a, v in first.items() if a in corpus}
    vec = {a: c["vec"] for a, c in corpus.items() if c["vec"]}
    print(f"\n=== {name} ===")
    print(f"distinct guest functions traced: {len(first)}")
    print(f"AUDIO CORPUS EXECUTED: {len(hit)} of {len(corpus)} ({100 * len(hit) / len(corpus):.1f}%)")
    print("  by thread of first call:")
    for t, n in collections.Counter(t for _, t in hit.values()).most_common(12):
        print(f"    {n:>5}  {t}")
    vh = [a for a in vec if a in hit]
    print(f"  vector functions executed: {len(vh)} of {len(vec)} "
          f"({sum(vec[a] for a in vh)} of {sum(vec.values())} vector instructions)")
    for a in sorted(vec, key=lambda a: -vec[a])[:12]:
        print(f"    sub_{a} {vec[a]:>5} vec  {ran(hit, a)}")
    print("  PLAN phase 2 targets:")
    for a, what in PHASE2.items():
        print(f"    sub_{a} {what:<20} {ran(hit, a)}")
    return hit

def main():
    corpus = json.load(open(sys.argv[1]))
    union = {}
    for path in sys.argv[2:]:
        header, first = load(path)
        print(f"\n{path}\n  {header}")
        hit = report(corpus, os.path.basename(path), first)
        for a, v in hit.items():
            union.setdefault(a, v)
        with open(path + ".audio_hits.tsv", "w") as fh:
            for a, (seq, t) in sorted(hit.items(), key=lambda kv: kv[1][0]):
                fh.write(f"sub_{a}\t{seq}\t{t}\n")
    if len(sys.argv) > 3:
        print(f"\n=== UNION of {len(sys.argv) - 2} traces: {len(union)} of {len(corpus)} ===")

if __name__ == "__main__":
    main()
