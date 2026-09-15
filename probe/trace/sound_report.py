#!/usr/bin/env python3
"""Group a played session's audio probe lines by the input script's markers.

    probe/trace/sound_report.py LOG [AUDIOFILES.BIG] [--every SECONDS]

LOG may also be a gzipped trace extract (probe/traces/sessions/LABEL.audio-trace.log.gz).
AUDIOFILES.BIG defaults to $SKATE_AUDIOFILES, then the Linux copy. The find_samples and list_exports
binaries come from $SKATE_AUDIO_EXAMPLES (default rust/skate-audio-formats/target/release/examples),
with `.exe` appended on Windows; build them with
`cargo build --release -p skate-audio-formats --example find_samples --example list_exports`.

--every groups by elapsed time instead of by marker, for a session played by hand (no script).
If a LABEL.pieces/ directory exists (hard links of every rotated piece, kept while the game ran),
its files are read in name order instead of the logger's own pieces.

The game's logger rotates at 5 MB into LABEL.1.log, LABEL.2.log, ... (higher is older) and keeps ten,
so the pieces are read oldest first and then LOG itself. A session that fills more than ten loses
its start; the report says so when the oldest piece does not begin at the session's first line.

For each marker window (from one `input script: t=... mark NAME` line to the next) it prints:
- the posts to each player sound object (`skate3-audio-msg`);
- the re-deliveries per object (`skate3-audio-update`);
- the voice opens per bank (`skate3-audio-open`), attributed by the EAAC header's second word at any
  slot with rust/skate-audio-formats' `find_samples` -- the descriptor index is not the slot in every
  bank -- with the objects that bank exports. A word several banks share lists them all;
- any wipeouts.

It ends with which player objects the whole session posted and which it never did. The marker names
are the script's intents; the posts are what the game did.
"""
import collections
import gzip
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent.parent
FORMATS = Path(os.environ.get("SKATE_AUDIO_EXAMPLES", HERE / "rust/skate-audio-formats/target/release/examples"))
EXE = ".exe" if os.name == "nt" else ""
PLAYER_OBJECTS = [
    "Class_Flips", "cloth_trick", "c_cloth_falls", "Class_Treatment", "Class_Squeaks", "Class_Seams",
    "Class_rolling", "Rolling_Rattle_Class", "Class_wheels_skid", "Class_grind", "c_board_slide",
    "c_body_slide", "playercharacter_footstep", "Class_foot_drag", "SenseOfSpeed_wind",
    "SenseOfSpeed_rattle", "c_foley_utility", "hall_of_meat_slo_mo",
]
STAMP = re.compile(r"^\[[\d-]+ (\d+):(\d+):([\d.]+)\]")


def seconds(line):
    m = STAMP.match(line)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def pieces(log):
    """The rotated pieces of `log`, oldest first, then `log`."""
    if log.name.endswith(".gz"):
        return [log]
    stem = log.name[:-len(".log")] if log.name.endswith(".log") else log.name
    kept = log.parent / (stem + ".pieces")
    if kept.is_dir() and any(kept.glob("*.log")):
        return sorted(kept.glob("*.log"))
    rotated = []
    for p in log.parent.glob(stem + ".*.log"):
        middle = p.name[len(stem) + 1:-len(".log")]
        if middle.isdigit():
            rotated.append((int(middle), p))
    return [p for _, p in sorted(rotated, reverse=True)] + [log]


def lines_of(log):
    for piece in pieces(log):
        opener = gzip.open if piece.name.endswith(".gz") else open
        with opener(piece, "rt", errors="replace") as f:
            yield from f


def main():
    args = sys.argv[1:]
    every = None
    if "--every" in args:
        i = args.index("--every")
        every = float(args[i + 1])
        del args[i:i + 2]
    log = Path(args[0])
    parts = pieces(log)
    print(f"reading {len(parts)} piece(s): {', '.join(p.name for p in parts)}")
    if len(parts) >= 11:
        print("   WARNING: ten rotated pieces - the logger keeps ten, so the session's start may be lost")
    archive = args[1] if len(args) > 1 else os.environ.get(
        "SKATE_AUDIOFILES", "/home/nakas/Documents/skate3/Skate3Recomp-Linux/game/data/audio/audiofiles.big")
    windows = [("(before the first marker)", None)]
    posts = collections.defaultdict(collections.Counter)
    updates = collections.defaultdict(collections.Counter)
    opens = collections.defaultdict(collections.Counter)
    wipeouts = collections.defaultdict(list)
    pairs = set()
    start = None
    bucket = -1
    for line in lines_of(log):
        t = seconds(line)
        if every is not None and t is not None:
            start = t if start is None else start
            # Threads log slightly out of order, so a bucket only ever moves forward.
            b = int((t - start) // every)
            if b > bucket:
                bucket = b
                windows.append(("t=%d:%02d" % divmod(int(b * every), 60), t))
        if "input script: t=" in line and (" mark " in line or " capture " in line):
            m = re.search(r"t=(\d+) ms (?:mark|capture) (\S+)", line)
            if m and " mark " in line:
                windows.append((m.group(2), t))
            continue
        w = windows[-1][0]
        if "WIPEOUT #" in line:
            wipeouts[w].append(line.split("input script: ")[-1].strip())
        elif "skate3-audio-msg: " in line:
            m = re.search(r"skate3-audio-msg: \d+ obj=\d+ (\S+)", line)
            if m:
                posts[w][m.group(1)] += 1
        elif "skate3-audio-update: " in line:
            m = re.search(r"skate3-audio-update: \d+ (\S+) node=", line)
            if m:
                updates[w][m.group(1)] += 1
        elif "skate3-audio-open: " in line:
            m = re.search(r"eaac=\[([0-9A-F]{8}) ([0-9A-F]{8})\] byte=\d+ desc=\[(?:[0-9A-F]{8} ){4}([0-9A-F]{8})", line)
            if m:
                key = "%x" % int(m.group(2), 16)
                pairs.add(key)
                opens[w][key] += 1

    # Attribute sample keys to banks, and banks to the objects they export.
    bank_of = collections.defaultdict(list)
    exports = {}
    if pairs:
        out = subprocess.run([str(FORMATS / ("find_samples" + EXE)), archive, *("*:" + k for k in sorted(pairs))],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            m = re.match(r"(\S+\.abk): \d+ of \d+ match \[([^\]]*)\]", line)
            if m:
                for hit in m.group(2).split():
                    word = hit.split(":")[1].split("@")[0]
                    if m.group(1) not in bank_of[word]:
                        bank_of[word].append(m.group(1))
        out = subprocess.run([str(FORMATS / ("list_exports" + EXE)), archive], capture_output=True, text=True).stdout
        for line in out.splitlines():
            m = re.match(r"(\S+\.abk) \(\d+ samples\): (.*)", line)
            if m:
                exports[m.group(1)] = m.group(2).split()

    seen = collections.Counter()
    for name, _ in windows:
        p, u, o, x = posts[name], updates[name], opens[name], wipeouts[name]
        if not (p or u or o or x):
            continue
        print(f"== {name}")
        player = {k: v for k, v in p.items() if k in PLAYER_OBJECTS}
        other = {k: v for k, v in p.items() if k not in PLAYER_OBJECTS}
        seen.update(player)
        if player:
            print("   player posts:  " + ", ".join(f"{k} {v}" for k, v in sorted(player.items())))
        if other:
            print("   other posts:   " + ", ".join(f"{k} {v}" for k, v in sorted(other.items())))
        if u:
            print("   updates:       " + ", ".join(f"{k} {v}" for k, v in sorted(u.items()) if k in PLAYER_OBJECTS))
        if o:
            by_bank = collections.Counter()
            for key, n in o.items():
                banks = bank_of.get(key) or ["(unattributed)"]
                by_bank[" / ".join(banks)] += n
            rows = []
            for bank, n in sorted(by_bank.items()):
                objs = [e for b in bank.split(" / ") for e in exports.get(b, []) if e in PLAYER_OBJECTS]
                rows.append(f"{bank} {n}" + (f" [{', '.join(sorted(set(objs)))}]" if objs else ""))
            print("   opens by bank: " + "; ".join(rows))
        for line in x:
            print("   " + line)
    print("== session coverage")
    print("   posted:     " + ", ".join(f"{k} {seen[k]}" for k in PLAYER_OBJECTS if seen[k]))
    print("   never:      " + ", ".join(k for k in PLAYER_OBJECTS if not seen[k]))


if __name__ == "__main__":
    main()
