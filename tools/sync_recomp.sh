#!/usr/bin/env bash
# Keep recomp/src (this repo, the edited copy) and skate3recomp-dev/src (what ninja builds) in step.
#
#   sync_recomp.sh push   copy recomp/src -> skate3recomp-dev/src; refuses if the destination
#                         drifted from what was last pushed (someone edited the build tree)
#   sync_recomp.sh pull   copy skate3recomp-dev/src -> recomp/src for the tracked file set
#   sync_recomp.sh diff   list files that differ in either direction (exit 1 if any)
#
# The file set is every skate3_*.cpp/.h directly under recomp/src plus recomp/src/audio_ports/
# recursively. recomp/src is a plain copy, not a symlink, so every edit must be pushed before a
# build or ninja compiles stale code and exits 0.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
SRC=$HERE/recomp/src
DST=${RECOMP_SRC:-/home/nakas/Documents/skate3/skate3recomp-dev/src}
STAMP=$HERE/recomp/.sync-stamp
cmd=${1:?usage: sync_recomp.sh push|pull|diff}

files() {  # relative paths of the synced set, from a root
  (cd "$1" && { find . -maxdepth 1 -type f \( -name 'skate3_*.cpp' -o -name 'skate3_*.h' \) ; find ./audio_ports -type f 2>/dev/null; } | sed 's#^\./##' | sort)
}
stamp_of() { (cd "$1" && files "$1" | xargs -r sha256sum); }

case "$cmd" in
  diff)
    rc=0
    for f in $(files "$SRC"); do
      if [ ! -f "$DST/$f" ]; then echo "only in recomp/src: $f"; rc=1
      elif ! cmp -s "$SRC/$f" "$DST/$f"; then echo "differs: $f"; rc=1; fi
    done
    for f in $(files "$DST"); do
      case "$f" in skate3_audio_*|skate3_input_script.cpp|audio_ports/*) [ -f "$SRC/$f" ] || { echo "only in build tree: $f"; rc=1; } ;; esac
    done
    exit $rc ;;
  push)
    if [ -f "$STAMP" ]; then
      # Anything in the build tree that is neither what we last pushed nor what we are about
      # to push was edited there directly. Refuse rather than overwrite it silently.
      while read -r sum f; do
        [ -f "$DST/$f" ] || continue
        cur=$(sha256sum "$DST/$f" | cut -d' ' -f1)
        new=$( [ -f "$SRC/$f" ] && sha256sum "$SRC/$f" | cut -d' ' -f1 || true)
        if [ "$cur" != "$sum" ] && [ "$cur" != "$new" ]; then
          echo "refusing: $DST/$f was edited in the build tree since the last push" >&2
          echo "run 'sync_recomp.sh pull' or resolve by hand, then push again" >&2
          exit 1
        fi
      done < "$STAMP"
    fi
    mkdir -p "$DST/audio_ports"
    n=0
    for f in $(files "$SRC"); do
      if ! cmp -s "$SRC/$f" "$DST/$f" 2>/dev/null; then
        install -D -m 644 "$SRC/$f" "$DST/$f"; n=$((n+1)); echo "pushed $f"
      fi
    done
    for f in $(files "$DST"); do
      case "$f" in audio_ports/*) [ -f "$SRC/$f" ] || { rm -f "$DST/$f"; echo "removed $f"; n=$((n+1)); } ;; esac
    done
    stamp_of "$DST" > "$STAMP"
    echo "push: $n file(s) changed" ;;
  pull)
    n=0
    for f in $(files "$DST"); do
      case "$f" in skate3_audio_*|skate3_input_script.cpp|audio_ports/*) ;; *) continue ;; esac
      if ! cmp -s "$DST/$f" "$SRC/$f" 2>/dev/null; then
        install -D -m 644 "$DST/$f" "$SRC/$f"; n=$((n+1)); echo "pulled $f"
      fi
    done
    stamp_of "$DST" > "$STAMP"
    echo "pull: $n file(s) changed" ;;
  *) echo "unknown command $cmd" >&2; exit 2 ;;
esac
