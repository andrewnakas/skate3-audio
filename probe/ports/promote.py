#!/usr/bin/env python3
"""Apply a session's verdicts to the queue and to each port file's STATUS header.

  promote.py SUMMARY.json --profile boot

Reads summarize_session.py's --json output. For each port with a `verified N` verdict it sets
the queue status, records the call count, and rewrites the .inc's STATUS line and
calls/session line so the file itself carries its evidence. A diverged verdict records the
divergence line and bumps attempts; anything else is left for the operator to read.

The .inc edit is deliberate duplication of queue.json: the file is what a reader opens, and a
STATUS of "verified" next to a call count is the claim that has to survive being read.
"""
import argparse, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PORTS = os.path.join(REPO, "recomp", "src", "audio_ports")

STATUS_WORD = {"verified": "verified", "diverged": "divergent", "uncalled": "uncalled",
               "budget-overflow": "gate-2 (window budget exceeded at run time)",
               "mostly-skipped": "pending (mostly skipped)"}
ENUM = {"verified": "kPortVerified", "divergent": "kPortDivergent", "uncalled": "kPortUncalled"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("summary")
    ap.add_argument("--profile", default="boot")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    s = json.load(open(a.summary))
    counts = {"verified": 0, "diverged": 0, "uncalled": 0, "other": 0}
    for name, v in sorted(s["verdicts"].items()):
        if not name.startswith("sub_"):
            continue
        addr = name[4:]
        inc = os.path.join(PORTS, f"sub_{addr}.inc")
        if not os.path.exists(inc):
            continue
        text = open(inc).read()
        # A gate label is a property of the FUNCTION; a session verdict is a property of one
        # run. Never let the second overwrite the first. This overwrote sub_82B33870's gate-1
        # with "uncalled" twice: both facts were true, but kPortUncalled is in PortShadowable,
        # so the label would arm the shadow branch on a function whose closure reaches an
        # indirect call. Today Windows() returning false still stops it; that is a second line
        # of defence, not a reason to mislabel.
        current = ""
        for line in text.splitlines():
            if line.startswith("// STATUS:"):
                current = line[len("// STATUS:"):].strip()
                break
        if current.startswith("gate-"):
            print(f"  {name}: keeping {current.split()[0]} (a verdict does not outrank a gate label)")
            continue
        verdict = v["verdict"]
        kind = verdict.split()[0]
        runs = verdict.split()[1] if " " in verdict else "0"
        census = s.get("census", {}).get(name, {})
        calls = census.get("calls") or (int(runs) if runs.isdigit() else 0)

        if kind == "verified":
            qstatus, word = "verified", "verified"
            counts["verified"] += 1
        elif kind == "diverged":
            qstatus, word = "divergent", "divergent"
            counts["diverged"] += 1
        elif kind == "uncalled":
            qstatus, word = "uncalled", "uncalled"
            counts["uncalled"] += 1
        else:
            counts["other"] += 1
            print(f"  {name}: {verdict} -- left alone, read it yourself")
            continue

        if a.dry_run:
            print(f"  would set {name} -> {qstatus} ({calls} calls)")
            continue

        # STATUS header line, and the enum in the SKATE3_PORT line when the verdict allows it
        text = re.sub(r"^// STATUS: .*$", f"// STATUS: {word}", text, count=1, flags=re.M)
        if kind in ENUM:
            text = re.sub(r"(SKATE3_PORT(?:_EX)?\(\w+,\s*skate3::audio::)kPort\w+",
                          rf"\g<1>{ENUM[kind]}", text, count=1)
        text = re.sub(rf"^(// calls/session: .*?){a.profile} \S+",
                      rf"\g<1>{a.profile} {calls}", text, count=1, flags=re.M)
        open(inc, "w").write(text)
        args = [f"status={qstatus}", f"calls.{a.profile}={calls}"]
        if kind == "diverged" and v.get("detail"):
            args.append("last_divergence=" + v["detail"][:200])
        subprocess.run([sys.executable, os.path.join(HERE, "queue.py"), "set", addr] + args,
                       check=True)
    print(f"promote: {counts}")


if __name__ == "__main__":
    main()
