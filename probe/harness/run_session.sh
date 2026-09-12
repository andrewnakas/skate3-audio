#!/usr/bin/env bash
# One recomp session for the audio harness: shadow-verify native ports, count calls, capture
# the guest mix.
#
# Boots through the demo path with frontend movies left to play, because the movie player is
# the first caller of the PacketPlayer command queue that EVENT_SUBMIT belongs to.
#
# The game ignores SIGTERM. With DURATION unset this execs the game in the foreground and you
# end it yourself (close the window or pkill -KILL -x skate3). With DURATION=N it runs the game
# in the background, waits N seconds (or for STOP_ON to appear in the log), SIGKILLs its OWN pid
# -- never by name, the build directory is shared with other launchers -- then removes the
# /dev/shm segment a killed game leaks (4.5 GiB each; three fill the tmpfs).
#
# Usage: run_session.sh LABEL [MACRO]  ->  $OUT/LABEL.log and $OUT/LABEL.guestmix.raw
set -euo pipefail
LABEL=${1:?usage: run_session.sh LABEL [MACRO]}
MACRO=${2:-}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${OUT:-$HERE/out}
case "$OUT" in /*) ;; *) echo "OUT must be absolute (it is cd'd into)" >&2; exit 2 ;; esac
BIN=${RECOMP_BIN:-/home/nakas/Documents/skate3/skate3recomp-dev/out/build/linux-release-jammy/skate3}
GAME=${GAME_ROOT:-/home/nakas/Documents/skate3/freeskate/runtime/game}
USER_SRC=${USER_SRC:-/home/nakas/Documents/skate3/freeskate/runtime/user}
FRAMES=${AUDIO_DUMP_FRAMES:-4000}
SHADOW=${SHADOW:-true}
# NATIVE=true runs the verified native functions for real. Shadow wins when both are on.
NATIVE=${NATIVE:-false}
MOVIES=${PLAY_MOVIES:-true}
# AUDIO_VECTORS_PATH records shadow comparisons as replayable vectors: the entry registers, the
# watched windows, and the bytes the ORIGINAL body produced. SHADOW_DIVERGED_ONLY keeps only the
# ones that diverged, which is what a port fix needs.
VECTORS=${AUDIO_VECTORS_PATH:-}
VECTORS_MAX=${AUDIO_VECTORS_MAX:-4096}
DIVERGED_ONLY=${SHADOW_DIVERGED_ONLY:-false}
# PORT_CENSUS counts every hooked audio function and logs the first four calls' registers.
CENSUS=${PORT_CENSUS:-false}
# INPUT_SCRIPT drives a pad timeline after gameplay (docs/input-harness.md).
SCRIPT=${INPUT_SCRIPT:-}
SETTLE_MS=${INPUT_SETTLE_MS:-3000}
# EXPECT_T: file of symbol names that must be strong (T) in the binary, one per line.
EXPECT=${EXPECT_T:-}
DURATION=${DURATION:-0}
STOP_ON=${STOP_ON:-}

if pgrep -x skate3 >/dev/null; then echo "skate3 is already running" >&2; exit 1; fi
# Shared-game lock. Other sessions on this machine (skate3loader-based pipelines) launch the same
# binary, and a loader launch closes a live game. A process check has a race window; this file
# is the contract instead: whoever holds it owns the game, and others wait. Held only while a
# DURATION session runs, removed on any exit.
LOCK=${SKATE3_GAME_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/skate3-game.lock}
if [ "$DURATION" != 0 ]; then
  if [ -e "$LOCK" ]; then
    holder=$(cat "$LOCK" 2>/dev/null || true)
    hpid=$(sed -n 's/^pid=//p' "$LOCK" 2>/dev/null || true)
    if [ -n "$hpid" ] && kill -0 "$hpid" 2>/dev/null; then
      echo "game lock held: $holder" >&2; exit 1
    fi
    echo "removing stale game lock ($holder)" >&2
  fi
  printf 'owner=sk8Audio port loop\npid=%s\nlabel=%s\nsince=%s\n' "$$" "$LABEL" "$(date -Is)" > "$LOCK"
  trap 'rm -f "$LOCK"' EXIT
fi
if [ "$(strings -a "$BIN" | grep -cx audio_dump_path)" -eq 0 ]; then
  echo "$BIN has no audio_dump_path - build the Phase 1 sources first" >&2; exit 1
fi
if [ -n "$EXPECT" ]; then
  # Check the artifact, never a build's exit status: an unlisted TU builds green and hooks nothing.
  weak=$(LC_ALL=C comm -23 <(grep -v "^#" "$EXPECT" | sed "/^$/d" | LC_ALL=C sort -u) \
                  <(nm "$BIN" | awk "\$2==\"T\"{print \$3}" | LC_ALL=C sort -u))
  if [ -n "$weak" ]; then
    echo "not strong in $BIN (still the lifted body):" >&2; echo "$weak" >&2; exit 2
  fi
fi
if [ -n "$SCRIPT" ]; then
  SCRIPT=$(realpath "$SCRIPT")
  python3 "$HERE/../trace/check_script.py" "$SCRIPT" >/dev/null || { echo "bad input script" >&2; exit 2; }
fi
if [ "$DURATION" != 0 ]; then
  [ -n "${DISPLAY:-}" ] || { echo "DISPLAY is unset; the game needs a display" >&2; exit 2; }
  avail_kb=$(df --output=avail /dev/shm | tail -1)
  if [ "$avail_kb" -lt $((6 * 1024 * 1024)) ]; then
    echo "/dev/shm has $((avail_kb / 1024)) MB free; remove leaked xenia_memory_* first" >&2; exit 2
  fi
fi
mkdir -p "$OUT"
[ -d "$OUT/user" ] || cp -a "$USER_SRC" "$OUT/user"
LOG=$OUT/$LABEL.log
RAW=$OUT/$LABEL.guestmix.raw
rm -f "$LOG" "$RAW" "$OUT/$LABEL.gdb.txt"
cd "$OUT"
args=(
  --game_data_root="$GAME"
  --user_data_root="$OUT/user"
  --log_file="$LOG"
  --fullscreen=false
  --skate3_demo_path=true
  --skate3_demo_path_signed_in=false
  --skate3_demo_path_play_movies="$MOVIES"
  --skate3_demo_path_input_settle_ms=2500
  --skate3_demo_path_input_delay_ms=600
  --skate3_audio_shadow="$SHADOW"
  --skate3_audio_native="$NATIVE"
  --skate3_audio_vectors_diverged_only="$DIVERGED_ONLY"
  --skate3_audio_port_census="$CENSUS"
  --audio_stats=true
  --audio_dump_path="$RAW"
  --audio_dump_max_frames="$FRAMES"
)
if [ -n "$VECTORS" ]; then
  args+=( "--skate3_audio_vectors_path=$VECTORS" "--skate3_audio_vectors_max=$VECTORS_MAX" )
fi
if [ -n "$SCRIPT" ]; then
  args+=( "--skate3_input_script=$SCRIPT" "--skate3_input_script_settle_ms=$SETTLE_MS" )
fi
[ -n "$MACRO" ] && args+=( "--skate3_demo_path_gameplay_inputs=$MACRO" )
# GDB_SCRIPT runs the session under gdb, output to $OUT/LABEL.gdb.txt (see crash.gdb).
if [ -n "${GDB_SCRIPT:-}" ]; then
  exec gdb -q -batch -x "$GDB_SCRIPT" --args "$BIN" "${args[@]}" > "$OUT/$LABEL.gdb.txt" 2>&1
fi
if [ "$DURATION" = 0 ]; then
  exec "$BIN" "${args[@]}"
fi

"$BIN" "${args[@]}" > "$OUT/$LABEL.stdout" 2>&1 &
PID=$!
start=$(date +%s)
while kill -0 "$PID" 2>/dev/null; do
  now=$(date +%s)
  if [ $((now - start)) -ge "$DURATION" ]; then break; fi
  if [ -n "$STOP_ON" ] && [ -f "$LOG" ] && grep -q -E "$STOP_ON" "$LOG"; then
    echo "stop marker seen after $((now - start)) s"; break
  fi
  sleep 2
done
if kill -0 "$PID" 2>/dev/null; then
  kill -KILL "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  echo "killed own skate3 pid $PID after $(( $(date +%s) - start )) s"
else
  wait "$PID" 2>/dev/null; rc=$?
  echo "skate3 exited on its own with status $rc after $(( $(date +%s) - start )) s -- check $LOG for a crash"
fi
if ! pgrep -x skate3 >/dev/null; then
  n=0
  for seg in /dev/shm/xenia_memory_*; do
    [ -e "$seg" ] || continue
    rm -f "$seg" && n=$((n + 1))
  done
  [ "$n" -gt 0 ] && echo "removed $n leaked /dev/shm segment(s)"
else
  echo "another skate3 is running; leaving /dev/shm alone" >&2
fi
echo "log: $LOG"
