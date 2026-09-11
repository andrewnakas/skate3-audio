#!/usr/bin/env bash
# Phase 0a: one traced game session. Needs the hook applied and built first
# (trace_hook.py apply, then rebuild).
#
# Arms at boot, records the first call of every guest function, and dumps
# SKATE3_TRACE_DELAY_MS after gameplay is reached (the tracer caps it at 120 s).
# The demo path clears language select, press start and the intro movie; MACRO is
# an optional pad sequence injected once gameplay settles (see freeskate/macros.toml).
# User data is copied into OUT so real saves are never written.
#
# The game ignores SIGTERM. Once the log shows "skate3 trace: DUMPED" the trace is
# complete; close the window or pkill -KILL -x skate3.
#
# Usage: run_trace.sh LABEL [MACRO]      -> $OUT/LABEL.log and $OUT/LABEL.log.trace
set -euo pipefail
LABEL=${1:?usage: run_trace.sh LABEL [MACRO]}
MACRO=${2:-}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${OUT:-$HERE/out}
BIN=${RECOMP_BIN:-/home/nakas/Documents/skate3/skate3recomp-dev/out/build/linux-release-jammy/skate3}
GAME=${GAME_ROOT:-/home/nakas/Documents/skate3/freeskate/runtime/game}
USER_SRC=${USER_SRC:-/home/nakas/Documents/skate3/freeskate/runtime/user}
DELAY=${SKATE3_TRACE_DELAY_MS:-120000}

if pgrep -x skate3 >/dev/null; then echo "skate3 is already running" >&2; exit 1; fi
if [ "$(nm "$BIN" | grep -c _skate3_seen)" -eq 0 ]; then
  echo "$BIN has no recording hook - run trace_hook.py apply and rebuild" >&2; exit 1
fi
mkdir -p "$OUT"
[ -d "$OUT/user" ] || cp -a "$USER_SRC" "$OUT/user"
LOG=$OUT/$LABEL.log
rm -f "$LOG" "$LOG.trace"
cd "$OUT"
args=(
  --game_data_root="$GAME"
  --user_data_root="$OUT/user"
  --log_file="$LOG"
  --fullscreen=false
  --skate3_demo_path=true
  --skate3_demo_path_signed_in=false
  --skate3_demo_path_input_settle_ms=2500
  --skate3_demo_path_input_delay_ms=600
  --skate3_trace=true
  --skate3_trace_mode=first
  --skate3_trace_arm=boot
  --skate3_trace_dump_delay_ms="$DELAY"
)
[ -n "$MACRO" ] && args+=( "--skate3_demo_path_gameplay_inputs=$MACRO" )
exec "$BIN" "${args[@]}"
