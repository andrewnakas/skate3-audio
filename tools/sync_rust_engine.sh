#!/usr/bin/env bash
# Copy the two audio crates into the Rust engine's workspace.
#
#   sync_rust_engine.sh push|diff
#
# sk8Audio is the source of truth: the crates are developed and tested here, against the
# verified C++ in recomp/src/audio_ports/, and vendored into the engine so that repo stays
# clonable on its own. Same arrangement as tools/sync_recomp.sh, and the same hazard: an edit
# made in the engine tree is invisible here until someone diffs.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
ENGINE=${SKATE_RUST_ENGINE:-/home/nakas/Documents/skate-3-rust-engine}
cmd=${1:?usage: sync_rust_engine.sh push|diff}
[ -d "$ENGINE" ] || { echo "engine not at $ENGINE (set SKATE_RUST_ENGINE)" >&2; exit 2; }

for crate in skate-audio-formats skate-audio-core; do
  src=$HERE/rust/$crate/
  dst=$ENGINE/crates/$crate/
  case "$cmd" in
    diff)
      # Cargo.lock and target/ are per-workspace, so they are never compared.
      rsync -ain --delete --exclude target --exclude Cargo.lock "$src" "$dst" | sed "s#^#$crate: #"
      ;;
    push)
      mkdir -p "$dst"
      rsync -a --delete --exclude target --exclude Cargo.lock "$src" "$dst"
      echo "pushed $crate"
      ;;
    *) echo "unknown command $cmd" >&2; exit 2 ;;
  esac
done
[ "$cmd" = diff ] && echo "(no lines above means the two trees agree)"
exit 0
