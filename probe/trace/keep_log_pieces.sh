#!/bin/bash
# Keep every rotated piece of a session's log while the game runs.
#
#   probe/trace/keep_log_pieces.sh LABEL [OUT]
#
# The game's logger rotates its log at 5 MB into LABEL.1.log .. LABEL.10.log and deletes the
# eleventh, which at the raised audio probe caps is about 140 s of play. This hard-links each piece
# into OUT/LABEL.pieces/ the moment it appears, numbered in the order it was first seen (a piece is
# first seen as LABEL.1.log, polls are 1 s and rotations about 11 s apart), then links the final
# LABEL.log once the game has been gone for 5 s. probe/trace/sound_report.py reads that directory.
# Start it just before or just after the session; it gives up if no skate3 appears within 180 s.
set -u
L=${1:?usage: keep_log_pieces.sh LABEL [OUT]}
OUT=${2:-$(cd "$(dirname "$0")/../harness" && pwd)/out}
D=$OUT/$L.pieces
mkdir -p "$D"; rm -f "$D"/*.log
declare -A seen; n=0; seen_game=0; idle=0; waited=0
while true; do
  for f in "$OUT/$L".[0-9]*.log; do
    [ -f "$f" ] || continue
    ino=$(stat -c %i "$f")
    if [ -z "${seen[$ino]:-}" ]; then
      n=$((n + 1)); seen[$ino]=1
      ln "$f" "$D/$(printf '%05d' $n).log"
    fi
  done
  if pgrep -x skate3 >/dev/null; then seen_game=1; idle=0
  elif [ $seen_game = 1 ]; then idle=$((idle + 1)); [ $idle -ge 5 ] && break
  else waited=$((waited + 1)); [ $waited -ge 180 ] && { echo "game never appeared"; exit 1; }
  fi
  sleep 1
done
[ -f "$OUT/$L.log" ] && ln "$OUT/$L.log" "$D/99999-final.log"
echo "kept $n rotated pieces plus the final log in $D ($(du -sh "$D" | cut -f1))"
