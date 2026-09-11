#!/usr/bin/env bash
# Summarize a scripted play session: what the script did, what the game decided, what the
# trace saw, and frames ready to look at.
#
# Usage: summarize_play.sh LABEL
set -uo pipefail
LABEL=${1:?usage: summarize_play.sh LABEL}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${OUT:-$HERE/out}
LOG=$OUT/$LABEL.log
strip() { sed -E 's/^\[[0-9-]+ ([0-9:.]+)\] \[[a-z]+\] \[[a-z]+\] \[t[0-9]+\] /\1 /'; }

echo "=== script: markers, bails, rate ==="
grep -E 'input script:' "$LOG" | grep -v 'input script: captured' | strip
echo "frames the script captured: $(grep -c 'input script: captured' "$LOG")"
echo
echo "=== boot and trace ==="
grep -E 'demo path: gameplay reached|skate3 trace: (ARMED|DUMPED)' "$LOG" | strip
echo
echo "=== window capture series ==="
tail -3 "$OUT/$LABEL.capture.log" 2>/dev/null
echo "window shots: $(ls "$OUT/$LABEL.window" 2>/dev/null | wc -l)"
echo
if [ -d "$OUT/$LABEL.frames" ]; then
  "$HERE/frames_to_png.sh" "$OUT/$LABEL.frames" 480
fi
if [ -f "$LOG.trace" ]; then
  echo
  echo "=== audio corpus coverage ==="
  python3 "$HERE/analyze_trace.py" "$OUT/corpus.json" "$OUT/run1_mapswitch.log.trace" "$LOG.trace" \
    | grep -E '^=== |AUDIO CORPUS|UNION|vector functions executed|PLAN phase 2|82B28B78|82B28CC0'
fi
