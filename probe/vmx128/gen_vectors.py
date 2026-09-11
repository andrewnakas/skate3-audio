#!/usr/bin/env python3
"""Generate adversarial float32 / int32 test vectors for the VMX128 bit-exactness probe.

Written once to a binary file that both the C++ and the Rust runner read, so the two
sides cannot disagree about their inputs. Deterministic: no RNG state crosses a language
boundary.

Layout: a flat array of little-endian uint32 lane values, 4 lanes per vector.
"""
import struct, sys

def f2b(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]

# Individually interesting lane values, as raw bit patterns.
LANES = []

def add(*vals):
    LANES.extend(vals)

# zeros and denormals
add(0x00000000, 0x80000000)                    # +0, -0
add(0x00000001, 0x80000001)                    # min denormal +/-
add(0x007FFFFF, 0x807FFFFF)                    # max denormal +/-
add(0x00400000, 0x80400000)                    # mid denormal +/-
# smallest normals
add(0x00800000, 0x80800000)
# ones, halves, twos
add(f2b(1.0), f2b(-1.0), f2b(0.5), f2b(-0.5), f2b(2.0), f2b(-2.0))
# rounding boundaries: 1+2^-23, 1+2^-24 (ties), 1+3*2^-24
add(0x3F800001, 0x3F800002, 0x3F800003)
# large finite
add(0x7F7FFFFF, 0xFF7FFFFF)                    # +/-FLT_MAX
add(f2b(1e30), f2b(-1e30), f2b(1e-30), f2b(-1e-30))
# infinities
add(0x7F800000, 0xFF800000)
# NaNs: QNaN default, QNaN with payload, SNaN, negative NaN
add(0x7FC00000, 0x7FC00001, 0x7FDEADBE, 0x7F800001, 0xFFC00000, 0xFFDEADBE)
# integer-valued floats and conversion edges
add(f2b(3.0), f2b(-3.0), f2b(3.5), f2b(-3.5), f2b(2.5), f2b(-2.5))
add(f2b(2147483520.0), f2b(-2147483648.0))     # near INT_MAX / INT_MIN
add(f2b(2147483648.0), f2b(4294967040.0))      # 2^31, near UINT_MAX
add(f2b(4294967296.0), f2b(-1.0e10))           # beyond UINT_MAX
add(f2b(32768.0), f2b(-32768.0), f2b(32767.0)) # 16-bit pack edges
# exp2/log2 domain probes
add(f2b(0.0), f2b(1.0), f2b(-1.0), f2b(10.0), f2b(-10.0), f2b(127.0), f2b(128.0),
    f2b(-126.0), f2b(-149.0), f2b(0.3010299957), f2b(23.0), f2b(0.1), f2b(3.14159265))
# rsqrt domain probes: exercise every one of the 32 table entries
for e in range(32):
    add(f2b(2.0 ** (e - 16)) | 0)
for m in range(0, 0x800000, 0x800000 // 24):
    add(0x3F800000 | m)                        # [1,2) mantissa sweep
# generic bit patterns (xorshift32, deterministic, no cross-language state)
s = 0x12345678
for _ in range(512):
    s ^= (s << 13) & 0xFFFFFFFF
    s ^= s >> 17
    s ^= (s << 5) & 0xFFFFFFFF
    LANES.append(s)

# Pad to a multiple of 4 lanes.
while len(LANES) % 4:
    LANES.append(0)

with open(sys.argv[1] if len(sys.argv) > 1 else "vectors.bin", "wb") as fh:
    fh.write(struct.pack("<I", len(LANES)))
    for v in LANES:
        fh.write(struct.pack("<I", v & 0xFFFFFFFF))

print(f"{len(LANES)} lanes = {len(LANES)//4} vectors")
