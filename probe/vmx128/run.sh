#!/usr/bin/env bash
# Phase 0b — VMX128 bit-exactness probe.
#
# Builds the C++ reference (RexGlue's own lowerings, verbatim) under GCC and under
# clang-20, the compiler the recomp itself is built with, plus the Rust candidate. Runs
# them all over the same adversarial vectors and bit-compares each C++ build with Rust.
#
# Needs no Ghidra, no game build, no game data and no play session.
set -euo pipefail
cd "$(dirname "$0")"

SDK="${REXGLUE_SDK:-/home/nakas/Documents/skate3/skate3recomp-dev/third_party/rexglue-sdk}"
export PATH="$HOME/.cargo/bin:$PATH"
[ -d "$SDK/include/rex" ] || { echo "set REXGLUE_SDK to the rexglue-sdk root" >&2; exit 1; }

echo "== generating vectors =="
python3 gen_vectors.py vectors.bin

echo "== building and running Rust candidate =="
(cd rust && RUSTFLAGS="-C target-cpu=native" cargo build --release --quiet)
./rust/target/release/rust_runner vectors.bin rust_results.bin

# C++23: rex/types.h needs std::byteswap.
for cc in gcc:g++ clang20:clang++-20; do
  tag=${cc%%:*}; cxx=${cc#*:}
  command -v "$cxx" >/dev/null || { echo "== $cxx not installed, skipping =="; continue; }
  for mode in plain pinned; do
    flags=""; [ "$mode" = pinned ] && flags="-DPIN_COMMUTATIVE_OPERAND_ORDER"
    "$cxx" -std=c++23 -O2 -march=native $flags \
        -I"$SDK/include" -I"$SDK/thirdparty/simde" cpp/runner.cpp -o "cpp_runner_${tag}_$mode" -lm
    "./cpp_runner_${tag}_$mode" vectors.bin "cpp_results_${tag}_$mode.bin" 2>/dev/null
    echo
    echo "########## $cxx, $mode, vs Rust ##########"
    python3 compare.py "cpp_results_${tag}_$mode.bin" rust_results.bin
  done
done
