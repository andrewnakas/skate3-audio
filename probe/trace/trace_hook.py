#!/usr/bin/env python3
"""Apply, remove or check the guest-trace recording hook in generated/skate3_init.h.

The tracer's cvars and controller are compiled into the recomp, but the hook that
actually records function entries is a local edit to this generated header (see the
comment at the top of src/skate3_guest_trace.cpp). Without it an armed trace dumps an
empty file.

The header is included by 127 objects (111 generated + 16 src), so either direction
costs a rebuild of those: 195 s wall at ninja -j10, measured 2026-09-11. `remove`
restores the header byte-for-byte, but with a new mtime, so the next build recompiles
the same objects back to stock. Codegen also regenerates the header and drops the edit.

Usage: trace_hook.py apply|remove|status [--header PATH]
"""
import argparse, sys

DEFAULT = "/home/nakas/Documents/skate3/skate3recomp-dev/generated/skate3_init.h"
BEGIN = "// ---- SKATE3 GUEST TRACE HOOK: local edit, not codegen output -----------------"
END = "// ---- end SKATE3 GUEST TRACE HOOK ---------------------------------------------"
HOOK = [
    BEGIN,
    "// Applied by sk8Audio probe/trace/trace_hook.py. Verbatim from the comment at the",
    "// top of src/skate3_guest_trace.cpp. Disarmed it costs two loads of a hot global",
    "// and a not-taken branch per guest call. Codegen regenerates this file and drops it.",
    'extern "C" uint32_t g_skate3_trace_gen;',
    'extern "C" uint32_t g_skate3_trace_all;',
    'extern "C" void skate3_trace_enter(const char* fn, const PPCContext& ctx, uint8_t* base);',
    "#undef REX_FUNC_PROLOGUE",
    "#define REX_FUNC_PROLOGUE()                                              \\",
    "  do {                                                                   \\",
    "    __builtin_assume(((size_t)base & 0x1F) == 0);                        \\",
    "    static uint32_t _skate3_seen = 0;                                    \\",
    "    const uint32_t _gen = g_skate3_trace_gen;                            \\",
    "    if (__builtin_expect((_gen != _skate3_seen) | g_skate3_trace_all,    \\",
    "                         0)) {                                           \\",
    "      _skate3_seen = _gen;                                               \\",
    "      if (_gen | g_skate3_trace_all)                                     \\",
    "        skate3_trace_enter(__func__, ctx, base);                         \\",
    "    }                                                                    \\",
    "  } while (0)",
    END,
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["apply", "remove", "status"])
    ap.add_argument("--header", default=DEFAULT)
    a = ap.parse_args()
    lines = open(a.header).read().split("\n")
    present = BEGIN in lines
    if a.action == "status":
        print("hook present" if present else "hook absent (stock header)")
        return
    if a.action == "apply":
        if present:
            sys.exit("hook already present")
        defs = [i for i, l in enumerate(lines) if l.startswith("#define REX_FUNC_PROLOGUE")]
        if len(defs) != 6:
            sys.exit(f"expected 6 REX_FUNC_PROLOGUE definitions, found {len(defs)}; header layout changed")
        # The prologue block closes with an inner and an outer #endif after its last definition.
        seen, end = 0, None
        for i in range(defs[-1], len(lines)):
            if lines[i].startswith("#endif"):
                seen += 1
                if seen == 2:
                    end = i
                    break
        if end is None:
            sys.exit("could not find the end of the prologue block")
        lines[end + 1:end + 1] = [""] + HOOK
        print(f"hook applied after line {end + 1}")
    else:
        if not present:
            sys.exit("hook not present")
        b, e = lines.index(BEGIN), lines.index(END)
        if b > 0 and lines[b - 1] == "":
            b -= 1
        del lines[b:e + 1]
        print("hook removed")
    open(a.header, "w").write("\n".join(lines))

if __name__ == "__main__":
    main()
