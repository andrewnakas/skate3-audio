#!/usr/bin/env bash
# One scripted play session: a traced game driven by an input script, plus a window capture
# series from skate3loader's capture.py. The game draws through GTK, so with
# GDK_BACKEND=x11 it is an X11 client under XWayland and its pixels can be read.
#
# Usage: run_play.sh LABEL SCRIPT [EVERY_S] [FOR_S]
#   -> out/LABEL.log, LABEL.log.trace, LABEL.frames/   (the script's @capture frames)
#      out/LABEL.window/, LABEL.capture.log              (the capture.py series)
#
# Refuses to start while any skate3 is running. Other sessions on this machine launch the
# game too, and skate3loader kills a live skate3 when it starts, so a collision loses both.
set -euo pipefail
LABEL=${1:?usage: run_play.sh LABEL SCRIPT [EVERY_S] [FOR_S]}
SCRIPT=$(realpath "${2:?usage: run_play.sh LABEL SCRIPT [EVERY_S] [FOR_S]}")
EVERY=${3:-2}
FOR=${4:-150}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${OUT:-$HERE/out}
CAPTURE=${CAPTURE_PY:-/home/nakas/Documents/skate3/skate3loader/scripts/capture.py}
export GDK_BACKEND=x11

if pgrep -x skate3 >/dev/null; then
  echo "a skate3 is already running - not starting" >&2
  exit 1
fi
mkdir -p "$OUT"
INPUT_SCRIPT="$SCRIPT" CAPTURE_EVERY_MS=0 "$HERE/run_trace.sh" "$LABEL" &
game=$!
pid=""
for _ in $(seq 1 150); do
  if ! kill -0 "$game" 2>/dev/null; then
    wait "$game"
    exit $?
  fi
  pid=$(pgrep -n -x skate3 || true)
  [ -n "$pid" ] && break
  sleep 0.2
done
[ -n "$pid" ] || { echo "game did not appear" >&2; exit 1; }
rm -rf "$OUT/$LABEL.window"
mkdir -p "$OUT/$LABEL.window"
python3 "$CAPTURE" "$OUT/$LABEL.window/shot" --pid "$pid" --every "$EVERY" --for "$FOR" \
  > "$OUT/$LABEL.capture.log" 2>&1 &
wait "$game"
