#!/usr/bin/env python3
"""Find every function that appends a record to the audio command ring.

Why this exists: `docs/command-queue.md` said there was one producer, then two. Both were found
by reading bodies, which is not a method that terminates. This searches the whole lifted corpus
instead, and it does so without the trap CLAUDE.md warns about -- grepping a struct offset like
`+0x30` returns noise, because unrelated structures share offsets, and three hunts in this project
failed that way.

The discriminator is a CONJUNCTION anchored on a specific global, not an offset:

  1. the function loads the audio System from 0x8307762C, which the lifted code forms as
     `ctx.rX.s64 = -2096693248;` (lis rX,-31993 -> 0x83070000) then `REX_LOAD_U32(rX + 30252)`;
  2. it reads the ring write offset at +0xCC (204) and the ring buffer at +0x30 (48) off one base;
  3. it ADDS those two values, which is the record pointer and is the step no coincidence of
     offsets produces;
  4. it stores through that pointer.

A hit is then classified by the order of two things: the store that publishes the advanced offset
back to +0xCC, and the stores that write the record. Publishing first is bug 1.

Every hit still has to be read. This narrows 47,652 functions to a list short enough to read.

  find_producers.py [--generated DIR] [--executed docs/audio-executed-set.txt]
"""
import argparse, os, re, sys

START = re.compile(r'DEFINE_REX_FUNC\((sub_[0-9A-F]+)\)')
LIS = re.compile(r'ctx\.(r\d+)\.s64 = -2096693248;')
LOAD = re.compile(r'ctx\.(r\d+)\.u64 = REX_LOAD_U32\(ctx\.(r\d+)\.u32 \+ (\d+)\);')
ADD = re.compile(r'ctx\.(r\d+)\.u64 = ctx\.(r\d+)\.u64 \+ ctx\.(r\d+)\.u64;')
STORE = re.compile(r'REX_STORE_U32\(ctx\.(r\d+)\.u32 \+ (\d+), ')

SYSTEM_GLOBAL = 30252   # 0x8307762C - 0x83070000
WRITE_OFFSET = 204      # +0xCC
RING = 48               # +0x30


def bodies(path):
    text = open(path, errors="ignore").read()
    for m in START.finditer(text):
        at = text.index("{", m.end())
        depth, i = 0, at
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield m.group(1), text[at:i]


def classify(lines):
    """Return (publishes_first, record_store_count) or None if this is not an append."""
    offsets, rings, pointers, publishes, records = {}, {}, {}, [], []
    for i, line in enumerate(lines):
        m = LOAD.search(line)
        if m:
            dst, src, off = m.group(1), m.group(2), int(m.group(3))
            if off == WRITE_OFFSET:
                offsets[dst] = i
            elif off == RING:
                rings[dst] = i
            continue
        m = ADD.search(line)
        if m:
            dst, a, b = m.groups()
            if (a in offsets and b in rings) or (a in rings and b in offsets):
                pointers[dst] = i
            continue
        m = STORE.search(line)
        if m:
            base, off = m.group(1), int(m.group(2))
            if off == WRITE_OFFSET:
                publishes.append(i)
            elif base in pointers and pointers[base] < i:
                records.append(i)
    if not publishes or not records:
        return None
    first = min(publishes)
    return (all(i > first for i in records), len(records))


def threads(path):
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3:
            out[parts[0].lower()] = parts[2].split("/")[0].strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated",
                    default="/home/nakas/Documents/skate3/skate3recomp-dev/generated")
    ap.add_argument("--executed", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "audio-executed-set.txt"))
    a = ap.parse_args()
    where = threads(a.executed)
    found, scanned = [], 0
    for f in sorted(x for x in os.listdir(a.generated)
                    if x.startswith("skate3_recomp.") and x.endswith(".cpp")):
        for name, body in bodies(os.path.join(a.generated, f)):
            scanned += 1
            regs = set(LIS.findall(body))
            if not regs:
                continue
            if not any(re.search(r'REX_LOAD_U32\(ctx\.' + r + r'\.u32 \+ %d\)' % SYSTEM_GLOBAL,
                                 body) for r in regs):
                continue
            verdict = classify(body.splitlines())
            if verdict is None:
                continue
            first, count = verdict
            found.append((name, f, first, count, where.get(name[4:].lower(), "")))
    print(f"scanned {scanned} functions")
    print(f"{len(found)} append to the audio command ring\n")
    bug = [x for x in found if x[2]]
    print(f"{len(bug)} publish the offset BEFORE storing the record (bug 1):\n")
    for name, f, _, count, thread in sorted(found):
        shape = "publishes first" if _ else "stores first"
        seen = thread if thread else "not reached in the traced sessions"
        print(f"  {name:16s} {f:22s} {count:2d} record word(s)  {shape:16s}  {seen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
