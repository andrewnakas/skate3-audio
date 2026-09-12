#!/usr/bin/env python3
"""Check port .inc files for the mistakes that otherwise cost a build cycle.

  lint.py [FILE ...]        default: every recomp/src/audio_ports/sub_*.inc

Checks, each earned by an actual failure or an actual near-miss:
  1. a helper using REX_LOAD_*/REX_STORE_* must take `uint8_t* base` -- those macros expand to
     code naming `base`, so a helper without it is a compile error (cost three rebuilds)
  2. the namespace must be port_<ADDR> matching the file name, and the SKATE3_PORT line must
     name the same address -- a mismatch compiles and hooks the wrong function
  3. Native and Windows must both exist, Windows must return bool on every path
  4. the four header comment lines must be present, so docs/ports.md can be regenerated
  5. a port with no spec.write() must name a result register, else it compares nothing
     (gate 4: the vacuous green)
  6. no __imp__ call from a port body -- callees go through GuestCall so a promoted callee is
     exercised (the brief's rule, invisible at compile time)
  7. spec.write() inside a loop with no bound in sight, flagged for a human read
  8. a cross-port reference must be to an EARLIER port in the SAME aggregator TU

Exit 1 if any check fails.
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PORTS = os.path.join(REPO, "recomp", "src", "audio_ports")
REX_USE = re.compile(r"REX_(?:MM_)?(?:LOAD|STORE)_U\d+\(|REX_RAW_ADDR\(")
HELPER = re.compile(r"^\s*(?:inline\s+|static\s+)*[\w:<>,\s*&]+?\b(\w+)\s*\(([^)]*)\)\s*\{",
                    re.M)


def load_aggregators():
    try:
        import json
        q = json.load(open(os.path.join(HERE, "queue.json")))
        return {a: r.get("agg") for a, r in q.items()}
    except Exception:
        return {}


AGG = load_aggregators()


def check(path):
    name = os.path.basename(path)
    addr = name.removeprefix("sub_").removesuffix(".inc")
    text = open(path).read()
    bad = []

    if not re.search(rf"^namespace port_{addr} \{{", text, re.M):
        bad.append(f"missing `namespace port_{addr} {{`")
    m = re.search(r"SKATE3_PORT(?:_EX)?\((\w+),", text)
    if not m:
        bad.append("missing the SKATE3_PORT line")
    elif m.group(1) != addr:
        bad.append(f"SKATE3_PORT names {m.group(1)}, file is {addr}")
    if "REX_FUNC(Native)" not in text:
        bad.append("missing REX_FUNC(Native)")
    if not re.search(r"bool Windows\(PPCContext&[^)]*\)", text):
        bad.append("missing Windows(PPCContext&, uint8_t*, PortSpec&)")
    for line in ("// STATUS:", "// calls/session:", "// note:"):
        if line not in text:
            bad.append(f"header line missing: {line}")
    if re.search(r"^// sub_" + addr, text, re.M) is None:
        bad.append("header must start with `// sub_<ADDR>  role: ...`")

    # 1. helpers that use the macros must take base
    for hm in HELPER.finditer(text):
        fname, params = hm.group(1), hm.group(2)
        if fname in ("REX_FUNC", "Native", "Windows", "if", "for", "while", "switch", "return",
                     "namespace"):
            continue
        start = hm.end()
        depth, i = 1, start
        while i < len(text) and depth:
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        body = text[start:i]
        if REX_USE.search(body) and "base" not in params:
            bad.append(f"helper {fname}() uses REX_LOAD/STORE but has no `uint8_t* base` parameter")

    # 5. no writes declared -> a result register must be named
    win_body = ""
    wm = re.search(r"bool Windows\([^)]*\)\s*\{", text)
    if wm:
        depth, i = 1, wm.end()
        while i < len(text) and depth:
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        win_body = text[wm.end():i]
        if "return" not in win_body:
            bad.append("Windows() never returns")
    if "spec.write(" not in win_body:
        if re.search(r"SKATE3_PORT(?:_EX)?\([^)]*kReturnNone", text):
            bad.append("declares no writes AND no result register: the comparison would be vacuous")

    # 8. a reference into another port's namespace compiles only if that port is in the SAME
    # aggregator TU and earlier in it -- manifests include in address order. Reusing a callee's
    # window arithmetic is worth keeping (it cannot drift), so the rule is ordering, not a ban.
    # Comments are stripped first: a note naming another port is not a dependency.
    code = re.sub(r"//[^\n]*", "", text)
    for other in sorted(set(re.findall(r"\bport_([0-9A-F]{8})::", code))):
        if other == addr:
            continue
        mine, theirs = AGG.get(addr), AGG.get(other)
        if mine is None or theirs is None or mine != theirs:
            bad.append(f"references port_{other}:: from another aggregator ({theirs} vs {mine}): "
                       f"a separate translation unit, so it can never be declared here")
        elif int(other, 16) > int(addr, 16):
            bad.append(f"references port_{other}::, which is included AFTER this file "
                       f"(address order): copy the value locally")

    # 6. no __imp__ from a port body
    if "__imp__" in text:
        bad.append("calls __imp__ directly; use GuestCall so a promoted callee is exercised")

    # 7. an unbounded-looking write loop is worth a human read
    for lm in re.finditer(r"(for|while)\s*\([^)]*\)\s*\{", win_body):
        seg = win_body[lm.end():lm.end() + 400]
        head = lm.group(0)
        # A range-for over a constexpr array in this file is bounded at compile time; so is any
        # loop whose header names a literal limit, a count read from the object, or a cap.
        bounded = (":" in head and re.search(r":\s*k\w+\)", head)) or \
                  re.search(r"(<\s*\d+|kMax|kPortMaxSpans|count|limit|&&\s*\w+\s*<)", head)
        if "spec.write(" in seg and not bounded:
            bad.append("spec.write() in a loop with no visible bound -- confirm it cannot exceed 32 spans")
            break
    return bad


def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(PORTS, "sub_*.inc")))
    fails = 0
    for path in files:
        bad = check(path)
        if bad:
            fails += 1
            print(os.path.basename(path))
            for b in bad:
                print(f"    {b}")
    print(f"lint: {len(files)} file(s), {fails} with findings")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
