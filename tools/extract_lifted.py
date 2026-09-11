#!/usr/bin/env python3
"""Extract RexGlue's lifted C++ for guest functions the decompiler cannot handle.

Ghidra's PowerPC models do not decode VMX128, Xenon's extended vector ISA, so the
~40 audio functions that use it decompile to `halt_baddata`. RexGlue does decode it,
emitting one C++ statement per instruction with the original mnemonic in a comment.

For vector DSP kernels that form is arguably the better reference anyway: it keeps the
lane structure visible, which decompiled C would hide behind scalar temporaries.

Usage: extract_lifted.py <addr-file> <out-dir> [--generated DIR]
"""
import argparse
import glob
import os
import re
import sys


def index_functions(generated):
    """addr -> (path, start_line) for every DEFINE_REX_FUNC in the lifted sources."""
    start = re.compile(r"DEFINE_REX_FUNC\(sub_([0-9A-F]{8})\)")
    index = {}
    for path in sorted(glob.glob(os.path.join(generated, "skate3_recomp.*.cpp"))):
        with open(path, errors="ignore") as fh:
            for n, line in enumerate(fh):
                m = start.search(line)
                if m:
                    index[m.group(1)] = (path, n)
    return index


def extract(path, start_line):
    """Return the function body starting at start_line, up to its closing brace."""
    out, depth, started = [], 0, False
    with open(path, errors="ignore") as fh:
        for n, line in enumerate(fh):
            if n < start_line:
                continue
            out.append(line)
            depth += line.count("{") - line.count("}")
            if "{" in line:
                started = True
            if started and depth <= 0:
                break
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("addrs")
    ap.add_argument("outdir")
    ap.add_argument("--generated",
                    default="/Users/nakas/skate3/skate3recomp-dev/generated")
    args = ap.parse_args()

    index = index_functions(args.generated)
    os.makedirs(args.outdir, exist_ok=True)

    wanted = [l.strip().upper() for l in open(args.addrs) if l.strip()]
    written, missing = 0, []
    for a in wanted:
        if a not in index:
            missing.append(a)
            continue
        path, line = index[a]
        body = extract(path, line)
        with open(os.path.join(args.outdir, f"sub_{a}.cpp"), "w") as fh:
            fh.write(f"// Lifted by RexGlue from {os.path.basename(path)}:{line + 1}\n")
            fh.write("// Ghidra cannot decode VMX128; this is the authoritative form.\n\n")
            fh.write(body)
        written += 1

    print(f"extracted {written} of {len(wanted)}")
    if missing:
        print("missing:", " ".join(missing[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
