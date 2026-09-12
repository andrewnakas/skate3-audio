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
if pgrep -x skate3 >/dev/null; then echo "a skate3 is live: not relinking the shared binary" >&2; exit 3; fi
tools/sync_recomp.sh push | tail -1
ninja -C "$B" -j10 skate3 | grep -E "error:|FAILED" || true
[ "${PIPESTATUS[0]}" -eq 0 ] || { echo "build failed" >&2; exit 1; }
weak=$(LC_ALL=C comm -23 "$EXPECT" <(nm "$B/skate3" | awk '$2=="T"{print $3}' | LC_ALL=C sort -u))
[ -z "$weak" ] || { echo "not strong:" >&2; echo "$weak" >&2; exit 2; }
# A port and its census hook cannot both exist; the census TU must not name an armed port.
dup=$(LC_ALL=C comm -12 "$EXPECT" <(grep -o 'sub_[0-9A-F]\{8\}' recomp/src/skate3_audio_census_all.cpp | LC_ALL=C sort -u))
[ -z "$dup" ] || { echo "in both the port manifests and the census TU:" >&2; echo "$dup" >&2; exit 2; }
echo "armed ports: $(wc -l < "$EXPECT"), all strong"
