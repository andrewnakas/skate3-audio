#!/usr/bin/env python3
"""Check an input script against the rules skate3_input_script.cpp enforces, before
spending a game session on a typo. Prints the timeline of markers.

Usage: check_script.py SCRIPT
"""
import sys

BUTTONS = {"up", "down", "left", "right", "start", "back", "l3", "r3", "lb", "rb", "a", "b", "x", "y"}
AXES = {"lx", "ly", "rx", "ry", "lt", "rt"}


def main():
    path = sys.argv[1]
    t, steps, errors, events = 0, 0, [], []
    for lineno, raw in enumerate(open(path), 1):
        line = raw.split("#", 1)[0].split()
        if not line:
            continue
        if line[0] in ("@mark", "@capture"):
            if len(line) < 2:
                errors.append(f"line {lineno}: {line[0]} needs a name")
            else:
                events.append((t, line[0][1:], line[1]))
            continue
        try:
            duration = int(line[0])
        except ValueError:
            duration = 0
        if duration <= 0:
            errors.append(f"line {lineno}: expected a positive duration, got {line[0]!r}")
            continue
        for tok in line[1:]:
            if "=" in tok:
                key, _, value = tok.partition("=")
                if key not in AXES:
                    errors.append(f"line {lineno}: unknown axis {key!r}")
                else:
                    try:
                        v = int(value)
                        lo, hi = (0, 100) if key in ("lt", "rt") else (-100, 100)
                        if not lo <= v <= hi:
                            errors.append(f"line {lineno}: {key}={v} is clamped to {lo}..{hi}")
                    except ValueError:
                        errors.append(f"line {lineno}: bad value in {tok!r}")
            elif tok not in BUTTONS:
                errors.append(f"line {lineno}: unknown button {tok!r}")
        steps += 1
        t += duration
    for at, kind, name in events:
        print(f"  {at:>6} ms  {kind:<7} {name}")
    print(f"{path}: {steps} steps, {len(events)} markers, {t} ms")
    for e in errors:
        print("  ERROR", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
