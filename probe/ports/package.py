#!/usr/bin/env python3
"""Build the per-function package a port author reads: lifted body, census entry, provenance.

  package.py ADDR [ADDR ...]            write one .md per address
  package.py --tier A -n 16             the next N pending in a tier, hottest first
  package.py --all-pending              every pending function

Writes to $SK8_PKG_DIR (default probe/ports/out/pkg). The body comes from tools/extract_lifted.py
so there is exactly one extractor in the tree.
"""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PKG = os.environ.get("SK8_PKG_DIR", os.path.join(HERE, "out", "pkg"))


def hot(rec):
    return max((v or 0) for v in rec["calls"].values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("addrs", nargs="*")
    ap.add_argument("--tier")
    ap.add_argument("-n", type=int, default=16)
    ap.add_argument("--all-pending", action="store_true")
    a = ap.parse_args()

    census = json.load(open(os.path.join(REPO, "probe", "screen", "out", "census.json")))
    queue = json.load(open(os.path.join(HERE, "queue.json")))
    addrs = [x.upper().removeprefix("SUB_") for x in a.addrs]
    if a.tier or a.all_pending:
        rows = [(x, r) for x, r in queue.items()
                if r["status"] == "pending" and not r["legacy"]
                and (a.tier is None or r["tier"] == a.tier)]
        rows.sort(key=lambda kv: (-hot(kv[1]), kv[1]["lines"]))
        addrs += [x for x, _ in (rows if a.all_pending else rows[:a.n])]

    os.makedirs(PKG, exist_ok=True)
    for addr in addrs:
        r = census.get(addr)
        if r is None:
            print(f"{addr}: not in the census", file=sys.stderr)
            continue
        body = subprocess.run([sys.executable, os.path.join(REPO, "tools", "extract_lifted.py"),
                               "--one", addr], capture_output=True, text=True).stdout
        q = queue[addr]
        entry = {k: v for k, v in r.items() if k != "store_provenance"}
        with open(os.path.join(PKG, f"sub_{addr}.md"), "w") as f:
            f.write(f"# Package for sub_{addr}\n\n")
            f.write(f"calls: {q['calls']}  thread: {q['thread']}  tier: {q['tier']}\n\n")
            f.write(f"## census\n```json\n{json.dumps(entry, indent=1)}\n```\n\n")
            f.write("## store provenance\n")
            if not r["store_provenance"]:
                f.write("(no stores)\n")
            for p in r["store_provenance"]:
                f.write(f"- line {p['line']} {p['mnem']} ea=`{p['ea']}` base={p['base']} "
                        f"off={p['off']} cls={p['cls']} assigned_at={p['assigned_at']}\n")
            f.write(f"\n## lifted body\n```cpp\n{body}```\n")
    print(f"wrote {len(addrs)} package(s) to {PKG}")
    for addr in addrs:
        print(addr)


if __name__ == "__main__":
    main()
