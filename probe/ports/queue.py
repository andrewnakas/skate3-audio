#!/usr/bin/env python3
"""The port queue: one record per audio-thread function, and the generators that read it.

  queue.py init --census probe/screen/out/census.json        build queue.json from the census
  queue.py merge-dynamic SUMMARY.json --profile boot         fill calls.<profile> and thread
  queue.py tiers                                             (re)assign tiers from gates + calls
  queue.py next --tier A -n 8                                 next pending functions, hottest first
  queue.py set ADDR key=value ...                             update one record
  queue.py manifests                                          write aggregator manifests + census TU
  queue.py report [--md docs/ports.md]                        status table

Record fields: name, tu, line, lines, vec, tier, status, gate, batch, attempts, calls{boot,play,map},
thread, agg, legacy, note, last_divergence.
status: pending | written | armed | verified | thin | partial | promoted | divergent | uncalled | gate1 | gate2 | gate3 | gate4
"""
import argparse, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
QUEUE = os.path.join(HERE, "queue.json")
PORTS_DIR = os.path.join(REPO, "recomp", "src", "audio_ports")

# Functions already hooked elsewhere; a second definition is a duplicate symbol at link time.
LEGACY = {
    "82B28C18": "skate3_audio_native.cpp", "82B28CC0": "skate3_audio_native.cpp",
    "82B28B78": "skate3_audio_native.cpp", "82B28A00": "skate3_audio_native.cpp",
    "82B48B28": "skate3_audio_native.cpp", "82B7F828": "skate3_audio_native.cpp",
    "82B4FD40": "skate3_audio_probe.cpp",
}
STATUSES = ("pending", "written", "armed", "verified", "thin", "partial", "promoted", "divergent", "uncalled",
            "gate1", "gate2", "gate3", "gate4")
PROFILES = ("boot", "play", "map")


def load():
    return json.load(open(QUEUE))


def save(q):
    json.dump(q, open(QUEUE, "w"), indent=1, sort_keys=True)


def agg_for(addr, tu, medians):
    n = tu.replace("skate3_recomp.", "").replace(".cpp", "")
    if n in ("66",):
        return "ports_66"
    if n in medians:
        return f"ports_{n}{'a' if addr <= medians[n] else 'b'}"
    return "ports_misc"


def cmd_init(a):
    census = json.load(open(a.census))
    by_tu = collections.defaultdict(list)
    for addr, r in census.items():
        by_tu[r["tu"].replace("skate3_recomp.", "").replace(".cpp", "")].append(addr)
    medians = {}
    for n in ("67", "68"):
        xs = sorted(by_tu.get(n, []))
        if xs:
            medians[n] = xs[len(xs) // 2 - 1]
    q = {}
    for addr, r in census.items():
        g = r["gate1"]
        q[addr] = {
            "name": None, "tu": r["tu"], "line": r["line"], "lines": r["lines"], "vec": r["vec"],
            "leaf": r["leaf"], "stores_present": r["stores_present"],
            "gate1": g["verdict"], "gate1_reason": g["reason"], "gate1_at": g["at"],
            "gate2_suspect": r["gate2_suspect"],
            "tier": None, "status": "pending", "gate": None, "batch": None, "attempts": 0,
            "calls": {p: None for p in PROFILES}, "thread": None,
            "agg": agg_for(addr, r["tu"], medians),
            "legacy": LEGACY.get(addr), "note": "", "last_divergence": None,
        }
    save(q)
    print(f"initialised {len(q)} records; aggregators: "
          f"{dict(collections.Counter(r['agg'] for r in q.values()))}; "
          f"legacy {sum(1 for r in q.values() if r['legacy'])}")


def cmd_merge(a):
    q = load()
    summary = json.load(open(a.summary))
    census = summary.get("census", {})
    n = 0
    for addr, rec in q.items():
        e = census.get("sub_" + addr)
        rec["calls"][a.profile] = int(e["calls"]) if e else 0
        if e and e.get("thread") and not rec["thread"]:
            rec["thread"] = e["thread"]
        n += 1
    save(q)
    print(f"merged {a.profile}: {sum(1 for r in q.values() if r['calls'][a.profile])} of {n} called")


def hot(rec):
    return max((v or 0) for v in rec["calls"].values())


def cmd_tiers(a):
    q = load()
    for addr, rec in q.items():
        if rec["legacy"]:
            rec["tier"] = "L"
            continue
        if rec["status"] in ("gate2",):
            rec["tier"] = "E"
            continue
        if rec["gate1_reason"] == "timebase" or (not rec["stores_present"] and rec["gate1"] == "pass" and rec.get("no_result")):
            rec["tier"] = "F"
        elif rec["gate1"] != "pass":
            rec["tier"] = "D"
        elif all(v == 0 for v in rec["calls"].values()):
            rec["tier"] = "U"
        elif rec["vec"]:
            rec["tier"] = "C"
        elif rec["leaf"]:
            rec["tier"] = "A"
        else:
            rec["tier"] = "B"
    save(q)
    print(dict(sorted(collections.Counter(r["tier"] for r in q.values()).items())))


def cmd_next(a):
    q = load()
    rows = [(addr, r) for addr, r in q.items()
            if r["status"] == "pending" and (a.tier is None or r["tier"] == a.tier) and not r["legacy"]]
    rows.sort(key=lambda kv: (-hot(kv[1]), kv[1]["lines"]))
    for addr, r in rows[:a.n]:
        print(f"{addr}\t{r['tier']}\t{r['tu']}\t{r['line']}\t{r['lines']}\t{r['vec']}\t{hot(r)}\t{r['agg']}")


def cmd_set(a):
    q = load()
    rec = q[a.addr.upper().removeprefix("SUB_")]
    for kv in a.assign:
        k, v = kv.split("=", 1)
        if k == "status" and v not in STATUSES:
            sys.exit(f"bad status {v}")
        if k in ("attempts", "batch", "lines"):
            v = int(v)
        elif k.startswith("calls."):
            rec["calls"][k[6:]] = int(v)
            continue
        rec[k] = v
    save(q)


def inc_path(addr):
    return os.path.join(PORTS_DIR, f"sub_{addr}.inc")


def cmd_manifests(a):
    q = load()
    os.makedirs(PORTS_DIR, exist_ok=True)
    aggs = collections.defaultdict(list)
    for addr, rec in sorted(q.items()):
        if rec["legacy"]:
            continue
        if os.path.exists(inc_path(addr)):
            aggs[rec["agg"]].append(addr)
    names = ("ports_66", "ports_67a", "ports_67b", "ports_68a", "ports_68b", "ports_misc")
    for name in names:
        path = os.path.join(PORTS_DIR, f"{name}.manifest.inc")
        with open(path, "w") as fh:
            fh.write(f"// Generated by probe/ports/queue.py manifests. Do not edit.\n")
            for addr in aggs.get(name, []):
                fh.write(f'#include "audio_ports/sub_{addr}.inc"\n')
    # census TU: every non-legacy function WITHOUT a port file
    census = [addr for addr, rec in sorted(q.items())
              if not rec["legacy"] and not os.path.exists(inc_path(addr))]
    write_census_tu(census, os.path.join(REPO, "recomp", "src", "skate3_audio_census_all.cpp"))
    print(f"manifests: {{{', '.join(f'{k}: {len(v)}' for k, v in sorted(aggs.items()))}}}; "
          f"census TU counts {len(census)}")


def write_census_tu(addrs, path):
    with open(path, "w") as fh:
        fh.write('''/**
 * @file        skate3_audio_census_all.cpp
 * @brief       Counting hooks on every audio-thread function that has no native port yet
 *
 * GENERATED by probe/ports/queue.py manifests from probe/ports/queue.json. Do not edit.
 *
 * Each hook counts the call, dumps the entry registers and thread name for the first four
 * calls, and forwards to the original. Cvar-gated (`skate3_audio_port_census`), so it costs a
 * load and a branch when off. As functions gain a port file the generator drops them from
 * here, because a second definition of the same symbol is a link error.
 */
#include "skate3_audio_port.h"

namespace {
constexpr const char* kNames[] = {
''')
        for addr in addrs:
            fh.write(f'    "sub_{addr}",\n')
        fh.write('''};
constexpr size_t kCount = sizeof(kNames) / sizeof(kNames[0]);
skate3::audio::CensusSlot g_slots[kCount ? kCount : 1]{};
skate3::audio::CensusTable g_table{kNames, g_slots, kCount};
struct RegisterOnLoad {
  RegisterOnLoad() { skate3::audio::RegisterCensusTable(g_table); }
} g_register;
}  // namespace

#define SKATE3_CENSUS_ALL(index, name)                              \\
  extern "C" REX_FUNC(name) {                                       \\
    skate3::audio::CensusHit(g_table, index, ctx);                  \\
    __imp__##name(ctx, base);                                       \\
  }

''')
        for i, addr in enumerate(addrs):
            fh.write(f"SKATE3_CENSUS_ALL({i}, sub_{addr})\n")


def cmd_sync_status(a):
    """Read each port file's STATUS header into the queue.

    promote.py sets a status from a session's verdict, but a gate-labelled port never produces
    a verdict -- the macro does not arm the shadow branch for it. Without this the queue reports
    a finished gate-1 body as "pending", which understates the work and, worse, keeps offering
    it to `next`.
    """
    q = load()
    counts = collections.Counter()
    for addr, rec in q.items():
        path = inc_path(addr)
        if not os.path.exists(path):
            continue
        header = ""
        for line in open(path):
            if line.startswith("// STATUS:"):
                header = line[len("// STATUS:"):].strip()
                break
        if not header:
            continue
        word = header.split()[0].lower().rstrip(":,")
        # A thin port's header still opens with "verified", because it IS verified -- what it
        # lacks is enough calls for its size to carry promotion (docs/promotion.md).
        if "but THIN" in header:
            word = "thin"
        mapped = {"verified": "verified", "promoted": "promoted", "divergent": "divergent",
                  "partial": "partial", "thin": "thin",
                  "uncalled": "uncalled", "gate-1": "gate1", "gate-2": "gate2",
                  "gate-3": "gate3", "gate-4": "gate4", "pending": "written"}.get(word)
        if mapped is None:
            print(f"  {addr}: unrecognised STATUS {header!r}")
            continue
        # A session's verdict outranks a file header: promote.py writes both, and a stale
        # "pending" header on a verified port must not undo the measurement.
        if rec["status"] in ("verified", "promoted") and mapped == "written":
            continue
        if rec["status"] != mapped:
            rec["status"] = mapped
            rec["gate"] = header if mapped.startswith("gate") else rec["gate"]
        counts[mapped] += 1
    save(q)
    print("sync-status:", dict(sorted(counts.items())))


def cmd_report(a):
    q = load()
    by = collections.Counter((r["tier"], r["status"]) for r in q.values())
    print("tier/status:", dict(sorted(by.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))))
    if a.md:
        with open(a.md, "w") as md:
            md.write("# Port status\n\nGenerated by `probe/ports/queue.py report`.\n\n")
            md.write("| addr | name | tier | status | gate | calls boot/play/map | lines | vec | attempts | note |\n")
            md.write("|---|---|---|---|---|---|---|---|---|---|\n")
            for addr, r in sorted(q.items(), key=lambda kv: (str(kv[1]["tier"]), -hot(kv[1]), kv[0])):
                c = r["calls"]
                md.write(f"| {addr} | {r['name'] or ''} | {r['tier']} | {r['status']} | {r['gate'] or ''} | "
                         f"{c['boot']}/{c['play']}/{c['map']} | {r['lines']} | {r['vec']} | {r['attempts']} | "
                         f"{r['note']} |\n")
        print(f"wrote {a.md}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--census", default=os.path.join(REPO, "probe", "screen", "out", "census.json")); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("merge-dynamic"); p.add_argument("summary"); p.add_argument("--profile", required=True, choices=PROFILES); p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("tiers"); p.set_defaults(fn=cmd_tiers)
    p = sub.add_parser("next"); p.add_argument("--tier"); p.add_argument("-n", type=int, default=8); p.set_defaults(fn=cmd_next)
    p = sub.add_parser("set"); p.add_argument("addr"); p.add_argument("assign", nargs="+"); p.set_defaults(fn=cmd_set)
    p = sub.add_parser("manifests"); p.set_defaults(fn=cmd_manifests)
    p = sub.add_parser("sync-status"); p.set_defaults(fn=cmd_sync_status)
    p = sub.add_parser("report"); p.add_argument("--md"); p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
