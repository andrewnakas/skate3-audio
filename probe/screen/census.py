#!/usr/bin/env python3
"""Static census of the audio-thread functions, against the four screening gates.

Reads every lifted TU once (the call graph must cover callees outside the audio set, since
gate 1 is transitive), then reports per function in the executed set filtered by thread:

  tu, line, lines, vec, leaf, callees, imports, indirect, timebase, lock,
  stores (by mnemonic), unaligned_vstores, stores_present,
  gate1 {verdict, reason, at, depth}     transitive over the callee closure
  store_provenance [{line, mnem, ea, base, off, cls, assigned_at}]
  gate2_suspect                           stores whose base is derived or in a loop
  closure_outside                         transitive callees outside the selected set

Provenance classes: entry (base register never assigned before the store, or a pure `mr`
alias of one), stack (base is r1), loop (between a label and a later backward goto to it),
derived (assigned earlier; the assigning line is cited). This is a screen, not a proof:
sub_82B50380 failed gate 2 by exactly the `derived` pattern, and the point of the table is
to make that visible before a port is written rather than after.

Usage: census.py [--generated DIR] [--executed docs/audio-executed-set.txt]
                 [--thread "RwAudioCore Dac"] [--out probe/screen/out/census.json]
                 [--md docs/ports-static.md]
"""
import argparse, collections, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

START = re.compile(r"DEFINE_REX_FUNC\(sub_([0-9A-F]{8})\)")
CALL = re.compile(r"\b(sub_[0-9A-F]{8})\(ctx,\s*base\)")
IMPORT = re.compile(r"\b__imp__([A-Za-z_][A-Za-z0-9_]*)\(ctx,\s*base\)")
HELPER = re.compile(r"\b__(save|rest)(gprlr|fpr|vmx)_\d+\(ctx,\s*base\)")
MNEM = re.compile(r"^\t// ([a-z][a-z0-9_.]*)\s?(.*)$")
VEC_PREFIXES = ("v", "lvx", "stvx", "lvlx", "lvrx", "stvlx", "stvrx", "lvsl", "lvebx", "lvehx",
                "lvewx", "stvebx", "stvehx", "stvewx", "mfvscr", "mtvscr")
STORE = re.compile(r"\bREX_(?:MM_)?STORE_U(8|16|32|64)\((.*?),\s")
VSTORE = re.compile(r"simde_mm_store(?:u)?_si128\(\(simde__m128i\*\)REX_RAW_ADDR\((.*?)\)")
EA_ASSIGN = re.compile(r"^\tea = (.*);$")
REG_ASSIGN = re.compile(r"^\t\s*ctx\.(r\d+)\.(?:u64|s64|u32|s32|u16|s16|u8|s8)\s*=[^=]")
MR_ALIAS = re.compile(r"^\t\s*ctx\.(r\d+)\.u64 = ctx\.(r\d+)\.u64;$")
BASE_REG = re.compile(r"ctx\.(r\d+)\.(?:u32|u64|s32|s64)")
LABEL = re.compile(r"^(loc_[0-9A-F]+):")
GOTO = re.compile(r"\bgoto (loc_[0-9A-F]+);")


def parse_all(generated):
    """One pass over every TU. Returns {addr: info} with body lines kept only for later use."""
    funcs = {}
    for path in sorted(glob.glob(os.path.join(generated, "skate3_recomp.*.cpp"))):
        tu = os.path.basename(path)
        with open(path, errors="ignore") as fh:
            lines = fh.readlines()
        i, n = 0, len(lines)
        while i < n:
            m = START.search(lines[i])
            if not m:
                i += 1
                continue
            addr, start = m.group(1), i
            depth, started = 0, False
            j = i
            while j < n:
                depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j]:
                    started = True
                if started and depth <= 0:
                    break
                j += 1
            body = lines[start:j + 1]
            funcs[addr] = analyse(addr, tu, start + 1, body)
            i = j + 1
    return funcs


def analyse(addr, tu, line1, body):
    callees, imports = set(), set()
    indirect = timebase = lock = vec = 0
    stores = collections.Counter()
    unaligned = 0
    last_mnem, last_mnem_idx, counted_idx = None, -1, -1
    last_ea = None
    assigned = {}          # reg -> line index of last assignment
    alias = {}             # reg -> entry reg it is a pure copy of
    labels, gotos = {}, []
    prov = []
    for k, line in enumerate(body):
        m = MNEM.match(line)
        if m:
            last_mnem, last_mnem_idx = m.group(1), k
            if last_mnem.startswith(VEC_PREFIXES):
                vec += 1
            continue
        m = LABEL.match(line)
        if m:
            labels[m.group(1)] = k
            continue
        for g in GOTO.findall(line):
            gotos.append((k, g))
        for c in CALL.findall(line):
            if c[4:] != addr:
                callees.add(c[4:])
        for c in IMPORT.findall(line):
            if not c.startswith("sub_"):
                imports.add(c)
        if "REX_CALL_INDIRECT_FUNC" in line:
            indirect += 1
        if "REX_QUERY_TIMEBASE" in line:
            timebase += 1
        if "REX_ENTER_GLOBAL_LOCK" in line:
            lock += 1
        m = EA_ASSIGN.match(line)
        if m:
            last_ea = (m.group(1), k)
        ea_expr = None
        m = STORE.search(line)
        if m:
            ea_expr = m.group(2)
        else:
            m = VSTORE.search(line)
            if m:
                ea_expr = m.group(1)
        if ea_expr is not None:
            mnem = last_mnem or "?"
            if last_mnem_idx != counted_idx:
                stores[mnem] += 1
                counted_idx = last_mnem_idx
                if mnem.startswith(("stvlx", "stvrx")):
                    unaligned += 1
                resolved = ea_expr
                if re.match(r"^ea\b", ea_expr) and last_ea is not None:
                    resolved = last_ea[0]
                regs = BASE_REG.findall(resolved)
                base = regs[0] if regs else None
                off = re.search(r"[+-]\s*(\d+)", resolved)
                if base == "r1":
                    cls, at = "stack", None
                elif base is None:
                    cls, at = "const", None
                elif base in assigned:
                    cls, at = "derived", assigned[base] + line1
                else:
                    cls, at = "entry", None
                    if base in alias:
                        base = f"{base}={alias[base]}"
                prov.append({"line": line1 + k, "mnem": mnem, "ea": resolved.strip(),
                             "base": base, "off": int(off.group(1)) if off else 0,
                             "cls": cls, "assigned_at": at})
        m = MR_ALIAS.match(line)
        if m and m.group(1) not in assigned and m.group(2) not in assigned:
            alias[m.group(1)] = alias.get(m.group(2), m.group(2))
            # a pure copy of an entry register: keep it 'entry' rather than 'derived'
            continue
        m = REG_ASSIGN.match(line)
        if m:
            assigned[m.group(1)] = k
            alias.pop(m.group(1), None)
    # loop classification: a store between label L and a later goto L is inside a loop
    for k, g in gotos:
        if g in labels and labels[g] < k:
            lo, hi = labels[g], k
            for p in prov:
                idx = p["line"] - line1
                if lo < idx < hi and p["cls"] in ("entry", "derived"):
                    p["cls"] = "loop"
    non_stack = [p for p in prov if p["cls"] != "stack"]
    return {
        "tu": tu, "line": line1, "lines": len(body), "vec": vec,
        "callees": sorted(callees), "imports": sorted(imports),
        "indirect": indirect, "timebase": timebase, "lock": lock,
        "stores": dict(stores), "unaligned_vstores": unaligned,
        "stores_present": bool(non_stack),
        "store_provenance": prov,
        "gate2_suspect": sum(1 for p in non_stack if p["cls"] in ("derived", "loop")),
    }


def gate1(funcs, addr, memo, stack=()):
    """Transitive gate-1 verdict. Cycles count as pass for the cycle edge."""
    if addr in memo:
        return memo[addr]
    if addr in stack:
        return {"verdict": "pass", "reason": None, "at": None, "depth": 0}
    f = funcs.get(addr)
    if f is None:
        r = {"verdict": "fail", "reason": "unlifted", "at": "sub_" + addr, "depth": 0}
        memo[addr] = r
        return r
    own = None
    if f["indirect"]:
        own = "indirect"
    elif f["imports"]:
        own = "import:" + ",".join(f["imports"])
    elif f["timebase"]:
        own = "timebase"
    elif f["lock"]:
        own = "lock"
    if own:
        r = {"verdict": "fail", "reason": own, "at": "sub_" + addr, "depth": 0}
        memo[addr] = r
        return r
    for c in f["callees"]:
        sub = gate1(funcs, c, memo, stack + (addr,))
        if sub["verdict"] == "fail":
            r = dict(sub)
            r["depth"] = sub["depth"] + 1
            memo[addr] = r
            return r
    r = {"verdict": "pass", "reason": None, "at": None, "depth": 0}
    memo[addr] = r
    return r


def closure(funcs, addr):
    seen, todo = set(), [addr]
    while todo:
        a = todo.pop()
        for c in funcs.get(a, {}).get("callees", []):
            if c not in seen:
                seen.add(c)
                todo.append(c)
    return seen


def read_executed(path, thread):
    rows = {}
    for line in open(path):
        if line.startswith("#") or not line.strip():
            continue
        addr, vec, thr = line.rstrip("\n").split("\t")
        if thr.startswith(thread):
            rows[addr] = thr
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated", default="/home/nakas/Documents/skate3/skate3recomp-dev/generated")
    ap.add_argument("--executed", default=os.path.join(REPO, "docs", "audio-executed-set.txt"))
    ap.add_argument("--thread", default="RwAudioCore Dac")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "census.json"))
    ap.add_argument("--md", default=os.path.join(REPO, "docs", "ports-static.md"))
    a = ap.parse_args()

    selected = read_executed(a.executed, a.thread)
    funcs = parse_all(a.generated)
    memo = {}
    out = {}
    for addr in sorted(selected):
        f = funcs.get(addr)
        if f is None:
            print(f"{addr}: not lifted", file=sys.stderr)
            continue
        g = gate1(funcs, addr, memo)
        cl = closure(funcs, addr)
        rec = {k: v for k, v in f.items()}
        rec["thread"] = selected[addr]
        rec["leaf"] = not f["callees"] and not f["imports"]
        rec["gate1"] = g
        rec["closure_outside"] = sorted(c for c in cl if c not in selected)
        rec["closure_size"] = len(cl)
        out[addr] = rec

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)

    total = len(out)
    g1 = sum(1 for r in out.values() if r["gate1"]["verdict"] == "pass")
    leaves = sum(1 for r in out.values() if r["leaf"])
    zero_store = sum(1 for r in out.values() if not r["stores_present"])
    reasons = collections.Counter(r["gate1"]["reason"].split(":")[0] for r in out.values()
                                  if r["gate1"]["verdict"] == "fail")
    print(f"selected {total} on thread '{a.thread}'; lifted functions {len(funcs)}")
    print(f"gate 1 pass {g1}, fail {total - g1} ({dict(reasons)}); leaves {leaves}; "
          f"zero non-stack stores {zero_store}")
    print(f"vec>0 {sum(1 for r in out.values() if r['vec'])}; "
          f"gate2 suspects {sum(1 for r in out.values() if r['gate2_suspect'])}")

    with open(a.md, "w") as md:
        md.write("# Static census of the audio-thread functions\n\n")
        md.write(f"Generated by `probe/screen/census.py` over `{os.path.basename(a.executed)}`, "
                 f"thread `{a.thread}`: {total} functions.\n\n")
        md.write("| addr | tu | line | lines | vec | leaf | gate1 | at | stores | g2 susp | unal |\n")
        md.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for addr, r in sorted(out.items(), key=lambda kv: (kv[1]["tu"], kv[0])):
            g = r["gate1"]
            st = sum(r["stores"].values())
            md.write(f"| {addr} | {r['tu'].replace('skate3_recomp.', '').replace('.cpp', '')} | "
                     f"{r['line']} | {r['lines']} | {r['vec']} | {'y' if r['leaf'] else ''} | "
                     f"{g['verdict'] if g['verdict'] == 'pass' else g['reason']} | "
                     f"{(g['at'] or '') + (f' d{g['depth']}' if g['depth'] else '')} | {st} | "
                     f"{r['gate2_suspect']} | {r['unaligned_vstores']} |\n")
    print(f"wrote {a.out} and {a.md}")


if __name__ == "__main__":
    main()
