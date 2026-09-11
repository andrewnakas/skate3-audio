#!/usr/bin/env python3
"""Resolve guest addresses to symbol names using the recomp's lifted sources.

The decompiled C names every callee `sub_<addr>` or `func_0x<addr>`, which hides
what the audio code actually calls out to. RexGlue's generated C++ does know: each
`// bl 0x<addr>` comment is followed by the call it lowered to, naming kernel imports
(`__imp__RtlEnterCriticalSection`) and compiler helpers (`__savegprlr_28`) explicitly.

Usage: resolve_callees.py <addr-file> [--generated DIR]
"""
import argparse
import collections
import glob
import os
import re
import sys

BL = re.compile(r"//\s*bl\s+0x([0-9a-f]{8})\s*$")
CALL = re.compile(r"^\s*(__imp__\w+|__\w+|sub_[0-9A-F]{8})\s*\(")


def build_map(generated):
    """addr -> symbol, learned from every `// bl` site in the lifted sources.

    The lifter emits the branch comment, then a `ctx.lr = ...;` line setting the
    return address, then the call itself -- so the call is not necessarily on the
    line straight after the comment. Look ahead a few lines.
    """
    names = {}
    for path in glob.glob(os.path.join(generated, "skate3_recomp.*.cpp")):
        pending, look = None, 0
        with open(path, errors="ignore") as fh:
            for line in fh:
                if pending:
                    m = CALL.match(line)
                    if m:
                        names.setdefault(pending, m.group(1))
                        pending = None
                        continue
                    look -= 1
                    if look <= 0:
                        pending = None
                    continue
                m = BL.search(line)
                if m:
                    pending, look = m.group(1).upper(), 3
    return names


def classify(sym):
    if sym is None:
        return "unresolved"
    if sym.startswith("__imp__"):
        return "kernel import"
    if sym.startswith("__"):
        return "compiler helper"
    return "guest function"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("addrs")
    ap.add_argument("--generated",
                    default="/Users/nakas/skate3/skate3recomp-dev/generated")
    args = ap.parse_args()

    names = build_map(args.generated)
    wanted = [l.strip().upper() for l in open(args.addrs) if l.strip()]

    groups = collections.defaultdict(list)
    for a in wanted:
        sym = names.get(a)
        groups[classify(sym)].append((a, sym))

    for kind in ("kernel import", "compiler helper", "guest function", "unresolved"):
        rows = sorted(groups.get(kind, []))
        if not rows:
            continue
        print(f"\n=== {kind} ({len(rows)}) ===")
        for a, sym in rows:
            print(f"  {a}  {sym or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
