#!/usr/bin/env bash
# Phase 1 session: shadow-verify native audio functions and capture the guest mix.
#
# Boots through the demo path with frontend movies left to play, because the movie
# player is the first caller of the PacketPlayer command queue that EVENT_SUBMIT belongs
# to. The shadow harness is armed, audio_stats reports the transport every 5 s, and
# audio_dump_path records the first AUDIO_DUMP_FRAMES submits.
#
# The game ignores SIGTERM. Close the window or pkill -KILL -x skate3; the capture is
# flushed per submit, so a killed session still leaves whole records.
#
# Usage: run_session.sh LABEL [MACRO]  ->  $OUT/LABEL.log and $OUT/LABEL.guestmix.raw
set -euo pipefail
LABEL=${1:?usage: run_session.sh LABEL [MACRO]}
MACRO=${2:-}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${OUT:-$HERE/out}
BIN=${RECOMP_BIN:-/home/nakas/Documents/skate3/skate3recomp-dev/out/build/linux-release-jammy/skate3}
GAME=${GAME_ROOT:-/home/nakas/Documents/skate3/freeskate/runtime/game}
USER_SRC=${USER_SRC:-/home/nakas/Documents/skate3/freeskate/runtime/user}
FRAMES=${AUDIO_DUMP_FRAMES:-4000}
SHADOW=${SHADOW:-true}
# NATIVE=true runs the verified native functions for real. Shadow wins when both are on.
NATIVE=${NATIVE:-false}
MOVIES=${PLAY_MOVIES:-true}
# AUDIO_VECTORS_PATH records every shadow comparison as a replayable vector for Phase 4:
# the entry registers, the watched windows, and the bytes the ORIGINAL body produced.
VECTORS=${AUDIO_VECTORS_PATH:-}
VECTORS_MAX=${AUDIO_VECTORS_MAX:-4096}
# KERNEL_CENSUS counts calls to the audio-thread VMX128 kernels. Breadth is not frequency:
# the guest tracer says each of them ran at least once and nothing about whether any is hot
# enough to be worth a 1,284-line hand translation.
CENSUS=${KERNEL_CENSUS:-false}

if pgrep -x skate3 >/dev/null; then echo "skate3 is already running" >&2; exit 1; fi
if [ "$(strings -a "$BIN" | grep -cx audio_dump_path)" -eq 0 ]; then
  echo "$BIN has no audio_dump_path - build the Phase 1 sources first" >&2; exit 1
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
  --audio_stats=true
  --audio_dump_path="$RAW"
  --audio_dump_max_frames="$FRAMES"
)
if [ -n "$VECTORS" ]; then
  args+=( "--skate3_audio_vectors_path=$VECTORS" "--skate3_audio_vectors_max=$VECTORS_MAX" )
fi
[ "$CENSUS" = true ] && args+=( --skate3_audio_kernel_census=true )
[ "${KERNEL_WINDOWS:-false}" = true ] && args+=( --skate3_audio_kernel_windows=true )
[ -n "$MACRO" ] && args+=( "--skate3_demo_path_gameplay_inputs=$MACRO" )
# GDB_SCRIPT runs the session under gdb, output to $OUT/LABEL.gdb.txt (see crash.gdb).
if [ -n "${GDB_SCRIPT:-}" ]; then
  exec gdb -q -batch -x "$GDB_SCRIPT" --args "$BIN" "${args[@]}" > "$OUT/$LABEL.gdb.txt" 2>&1
fi
exec "$BIN" "${args[@]}"
