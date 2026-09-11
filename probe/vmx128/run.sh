#!/usr/bin/env bash
# Phase 0b — VMX128 bit-exactness probe.
#
# Builds the C++ reference (RexGlue's own lowerings, verbatim) and the Rust
# candidate, runs both over the same adversarial vectors, and bit-compares.
#
# Needs no Ghidra, no game build, no game data and no play session.
set -euo pipefail
cd "$(dirname "$0")"

SDK="${REXGLUE_SDK:-/home/nakas/Documents/skate3/skate3recomp-dev/third_party/rexglue-sdk}"
export PATH="$HOME/.cargo/bin:$PATH"

[ -d "$SDK/include/rex" ] || { echo "set REXGLUE_SDK to the rexglue-sdk root" >&2; exit 1; }

echo "== generating vectors =="
python3 gen_vectors.py vectors.bin

echo "== building C++ reference (C++23: rex/types.h needs std::byteswap) =="
for mode in plain pinned; do
  flags=""; [ "$mode" = pinned ] && flags="-DPIN_COMMUTATIVE_OPERAND_ORDER"
  g++ -std=c++23 -O2 -march=native $flags \
      -I"$SDK/include" -I"$SDK/thirdparty/simde" cpp/runner.cpp -o "cpp_runner_$mode" -lm
done

echo "== building Rust candidate =="
(cd rust && RUSTFLAGS="-C target-cpu=native" cargo build --release --quiet)

echo "== running =="
./cpp_runner_plain  vectors.bin cpp_results_plain.bin
./cpp_runner_pinned vectors.bin cpp_results_pinned.bin
./rust/target/release/rust_runner vectors.bin rust_results.bin

echo
echo "########## RexGlue as written (plain intrinsics) vs Rust ##########"
python3 compare.py cpp_results_plain.bin rust_results.bin || true
echo
echo "########## operand order pinned (the translation rule) vs Rust ##########"
python3 compare.py cpp_results_pinned.bin rust_results.bin
