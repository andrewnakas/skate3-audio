#!/usr/bin/env bash
# One build step of the port loop: lint, manifests, push, build, then prove the artifact.
#
# Writes the EXPECTED list from the generated manifests, not from the directory listing: a port
# file that lands after `queue.py manifests` ran is still hooked by the census TU, which is also
# a strong T symbol, so a directory-derived list silently marks it "armed" when it is not.
#
# Usage: cycle_build.sh OUT_EXPECT_FILE
set -euo pipefail
HERE=$(cd "$(dirname "$0")/../.." && pwd)
EXPECT=${1:?usage: cycle_build.sh OUT_EXPECT_FILE}
B=${RECOMP_BUILD:-/home/nakas/Documents/skate3/skate3recomp-dev/out/build/linux-release-jammy}
cd "$HERE"
python3 probe/ports/lint.py
python3 probe/ports/queue.py manifests
grep -ho 'sub_[0-9A-F]\{8\}' recomp/src/audio_ports/*.manifest.inc | LC_ALL=C sort -u > "$EXPECT"
# The build directory is shared: relinking under a live game swaps the binary another session
# launched. Wait for the field to clear rather than failing the cycle, since a session of ours
# that is still exiting clears within seconds.
for _ in $(seq 1 60); do
  pgrep -x skate3 >/dev/null || break
  sleep 5
done
if pgrep -x skate3 >/dev/null; then
  echo "a skate3 is still live after 5 minutes: not relinking the shared binary" >&2; exit 3
fi
tools/sync_recomp.sh push | tail -1
# Capture ninja's own status. The previous form piped it through grep and `|| true`, which made
# PIPESTATUS describe `true` -- a failed build printed its error and then reported success, and
# the session that followed ran on the OLD binary. Caught only because the summarizer reports a
# census-only function as "census", never "verified".
NINJA_LOG=$(mktemp)
if ! ninja -C "$B" -j10 skate3 > "$NINJA_LOG" 2>&1; then
  grep -E "error:|FAILED" "$NINJA_LOG" | head -20 >&2
  rm -f "$NINJA_LOG"
  echo "build failed" >&2; exit 1
fi
rm -f "$NINJA_LOG"
# The artifact must be newer than every port it is supposed to contain. nm alone cannot tell a
# port hook from a stale census hook for the same address: both are strong T symbols.
SRC_TREE=${RECOMP_SRC:-/home/nakas/Documents/skate3/skate3recomp-dev/src}
stale=$(find "$SRC_TREE/audio_ports" -name '*.inc' -newer "$B/skate3" | head -5)
if [ -n "$stale" ]; then
  echo "binary is older than these port sources -- the build did not take:" >&2; echo "$stale" >&2; exit 2
fi
weak=$(LC_ALL=C comm -23 "$EXPECT" <(nm "$B/skate3" | awk '$2=="T"{print $3}' | LC_ALL=C sort -u))
[ -z "$weak" ] || { echo "not strong:" >&2; echo "$weak" >&2; exit 2; }
# A port and its census hook cannot both exist; the census TU must not name an armed port.
dup=$(LC_ALL=C comm -12 "$EXPECT" <(grep -o 'sub_[0-9A-F]\{8\}' recomp/src/skate3_audio_census_all.cpp | LC_ALL=C sort -u))
[ -z "$dup" ] || { echo "in both the port manifests and the census TU:" >&2; echo "$dup" >&2; exit 2; }
echo "armed ports: $(wc -l < "$EXPECT"), all strong"
