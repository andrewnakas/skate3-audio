#!/usr/bin/env python3
"""Turn one session log into a per-function verdict, and an exit code the loop can branch on.

  summarize_session.py LOG [--expect sub_A,sub_B,...] [--expect-file F] [--json OUT] [--md]
                           [--skip-threshold 0.10] [--min-runs 1]

Verdicts, per expected function name (the name a hook logs under):
  verified N        runs >= min-runs, no register/memory divergence, no overflow, skip fraction
                    below the threshold
  diverged          at least one divergence; the first divergence line is kept verbatim
  mostly-skipped    compared, but skipped calls exceed the threshold
  budget-overflow   a window set exceeded the harness budget (hard fail, never compared)
  native N          promoted body ran N times (a NATIVE session)
  uncalled          no runs line, no census count -- the game never reached it
  census N          not armed, but the census counted it (a census-only session)

A missing runs line is never green. Exit 1 unless every expected function is verified, native,
uncalled or census; exit 2 if the session did not reach gameplay or logged a crash.
"""
import argparse, json, re, sys

RUNS = re.compile(r"skate3-audio-shadow: (\S+) runs=(\d+) diverged: registers=(\d+) memory=(\d+)"
                  r"(?: skipped=(\d+) overflow=(\d+))?")
DIV = re.compile(r"skate3-audio-shadow: (\S+) run (\d+) diverges in (register|memory) (.*)$")
SKIP_LEGACY = re.compile(r"skate3-audio-shadow: (\S+) not comparable on (\d+) calls")
OVERFLOW = re.compile(r"skate3-audio-shadow: (\S+) (?:budget overflow|watches more than)")
NATIVE = re.compile(r"skate3-audio-native: (\S+) native runs=(\d+)")
CENSUS = re.compile(r"skate3-audio-census: (\S+) calls=(\d+)(?: thread=(\S+))?")
CENSUS_FIRST = re.compile(r"skate3-audio-census: (\S+) call=(\d+) thread=(\S+) (.*)$")
KCENSUS = re.compile(r"skate3-kernel-census: (\S+) calls=(\d+)")
STATS = re.compile(r"Audio stats \(([\d.]+)s\): .*?\(([\d.]+)/s, real-time=([\d.]+)/s\)")
GAMEPLAY = re.compile(r"demo path: gameplay reached|gameplay context 1")
# A graceful close (window closed by something outside the harness) ends a session early and
# silently shrinks its coverage: rarely-called functions then read as "uncalled".
WINDOW_CLOSE = re.compile(r"Window closing, shutting down")
CRASH = re.compile(r"\b(SIGSEGV|SIGFPE|SIGABRT|crash handler|Unhandled exception|fatal)\b", re.I)
TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\]")


def parse(path):
    fn = {}
    first_ts = last_ts = None
    gameplay = False
    crash = None
    closed = None
    stats = []
    for line in open(path, errors="ignore"):
        m = TS.match(line)
        if m:
            last_ts = m.group(1)
            first_ts = first_ts or last_ts
        if not gameplay and GAMEPLAY.search(line):
            gameplay = True
        if crash is None and CRASH.search(line) and "crash_report" not in line and "dump_on_crash" not in line:
            crash = line.strip()
        if closed is None and WINDOW_CLOSE.search(line):
            closed = last_ts
        m = STATS.search(line)
        if m:
            stats.append((float(m.group(2)), float(m.group(3))))
        m = RUNS.search(line)
        if m:
            e = fn.setdefault(m.group(1), {})
            e.update(runs=int(m.group(2)), reg=int(m.group(3)), mem=int(m.group(4)))
            if m.group(5) is not None:
                e.update(skipped=int(m.group(5)), overflow=int(m.group(6)))
            continue
        m = DIV.search(line)
        if m:
            e = fn.setdefault(m.group(1), {})
            e.setdefault("first_divergence", line.strip())
            continue
        m = SKIP_LEGACY.search(line)
        if m:
            fn.setdefault(m.group(1), {})["skipped"] = int(m.group(2))
            continue
        m = OVERFLOW.search(line)
        if m:
            e = fn.setdefault(m.group(1), {})
            e["overflow"] = max(1, e.get("overflow", 0))
            e.setdefault("first_overflow", line.strip())
            continue
        m = NATIVE.search(line)
        if m:
            fn.setdefault(m.group(1), {})["native"] = int(m.group(2))
            continue
        m = CENSUS_FIRST.search(line)
        if m:
            e = fn.setdefault(m.group(1), {})
            e.setdefault("thread", m.group(3))
            e.setdefault("first_calls", []).append(m.group(4))
            continue
        m = CENSUS.search(line) or KCENSUS.search(line)
        if m:
            e = fn.setdefault(m.group(1), {})
            e["calls"] = int(m.group(2))
            if m.lastindex and m.lastindex >= 3 and m.group(3):
                e.setdefault("thread", m.group(3))
    return fn, dict(first_ts=first_ts, last_ts=last_ts, gameplay=gameplay, crash=crash,
                    window_closed_at=closed,
                    stats_last=stats[-1] if stats else None,
                    stats_min_rate=min((s[0] for s in stats), default=None))


def verdict(e, skip_threshold, min_runs):
    if e is None:
        return "uncalled", None
    if e.get("overflow"):
        return "budget-overflow", e.get("first_overflow")
    runs = e.get("runs")
    if runs is not None:
        if e.get("reg") or e.get("mem") or e.get("first_divergence"):
            return "diverged", e.get("first_divergence")
        skipped = e.get("skipped", 0)
        if runs + skipped > 0 and skipped / (runs + skipped) > skip_threshold:
            return "mostly-skipped", f"skipped {skipped} of {runs + skipped}"
        if runs >= min_runs:
            return f"verified {runs}", None
        return "uncalled", f"runs {runs} below {min_runs}"
    if e.get("native"):
        return f"native {e['native']}", None
    if e.get("skipped"):
        return "mostly-skipped", f"skipped {e['skipped']}, compared 0"
    if e.get("calls"):
        return f"census {e['calls']}", e.get("thread")
    return "uncalled", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--expect", default="")
    ap.add_argument("--expect-file")
    ap.add_argument("--json")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--skip-threshold", type=float, default=0.10)
    ap.add_argument("--min-runs", type=int, default=1)
    a = ap.parse_args()

    fn, session = parse(a.log)
    expect = [x for x in a.expect.split(",") if x]
    if a.expect_file:
        expect += [l.strip() for l in open(a.expect_file) if l.strip() and not l.startswith("#")]
    names = expect or sorted(fn)

    rows, bad = [], 0
    for name in names:
        v, detail = verdict(fn.get(name), a.skip_threshold, a.min_runs)
        ok = v.startswith(("verified", "native", "uncalled", "census"))
        bad += not ok
        rows.append((name, v, detail or ""))

    session_bad = (not session["gameplay"]) or bool(session["crash"])
    out = {"session": session, "functions": fn,
           "verdicts": {n: {"verdict": v, "detail": d} for n, v, d in rows},
           "census": {n: {"calls": e.get("calls", 0), "thread": e.get("thread")}
                      for n, e in fn.items() if "calls" in e}}
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)

    if a.md:
        print("| function | verdict | detail |\n|---|---|---|")
        for n, v, d in rows:
            print(f"| {n} | {v} | {d} |")
    else:
        for n, v, d in rows:
            print(f"{n:<14} {v:<18} {d}")
    s = session
    print(f"-- session: gameplay={'yes' if s['gameplay'] else 'NO'} crash={s['crash'] or 'none'} "
          f"audio={s['stats_last']} min_rate={s['stats_min_rate']} span={s['first_ts']}..{s['last_ts']}")
    if s.get("window_closed_at"):
        print(f"-- WARNING: the window was closed at {s['window_closed_at']} -- the session ended "
              f"early, so an 'uncalled' verdict here is weaker than usual")
    print(f"-- {len(rows)} expected, {bad} not green")
    if session_bad:
        sys.exit(2)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
