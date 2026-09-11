#!/usr/bin/env bash
# Convert captured PPM frames to small PNGs for viewing, and delete the PPMs.
# Usage: frames_to_png.sh DIR [WIDTH]
set -euo pipefail
DIR=${1:?usage: frames_to_png.sh DIR [WIDTH]}
WIDTH=${2:-640}
shopt -s nullglob
n=0
for f in "$DIR"/*.ppm; do
  ffmpeg -loglevel error -y -i "$f" -vf "scale=${WIDTH}:-2" "${f%.ppm}.png" && rm -f "$f"
  n=$((n + 1))
done
echo "converted $n frames in $DIR"
