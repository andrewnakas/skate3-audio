#!/usr/bin/env python3
"""Compare the C++ reference and Rust candidate result files, per op and per FTZ state."""
import struct, sys

OPS = ["vaddfp128","vsubfp128","vmulfp128","vmaddfp","vnmsubfp","vmaxfp128","vminfp128",
       "vrefp","vrsqrtefp","vrfiz128","vmsum3fp128","vmsum4fp128","vcmpeqfp128",
       "vcmpgefp128","vcmpgtfp128","vexptefp128","vlogefp128","vcsxwfp128_0",
       "vcsxwfp128_15","vcuxwfp128_0","vcfpsxws128","vcfpuxws128","vperm128","vsel",
       "vand128","vandc128","vor128","vnor128","vxor128","vaddshs","vaddsws","vsubsws",
       "vadduwm","vpkshus128","vpkswss128","vsraw128","vslw128","vsrw128","vupkhsb128",
       "vmrghw128","vmrglw128","vspltw128","vsldoi128","lvx128_swap","lvlx128_swap5"]

a = open(sys.argv[1] if len(sys.argv)>1 else "cpp_results.bin","rb").read()
b = open(sys.argv[2] if len(sys.argv)>2 else "rust_results.bin","rb").read()
nvec = int(sys.argv[3]) if len(sys.argv)>3 else 158
assert len(a)==len(b), (len(a),len(b))

stride = nvec*16
bad = {}
for ftz in range(2):
    for oi,op in enumerate(OPS):
        off = (ftz*len(OPS) + oi)*stride
        sa, sb = a[off:off+stride], b[off:off+stride]
        if sa != sb:
            # count differing lanes and grab first example
            diffs=[]
            for v in range(nvec):
                for l in range(4):
                    o = v*16+l*4
                    x = struct.unpack_from("<I",sa,o)[0]
                    y = struct.unpack_from("<I",sb,o)[0]
                    if x!=y: diffs.append((v,l,x,y))
            bad[(op,ftz)] = diffs

total_lanes = len(OPS)*nvec*4*2
print(f"ops={len(OPS)} vectors={nvec} ftz states=2  -> {total_lanes} lane comparisons")
print()
if not bad:
    print("ALL OPS BIT-IDENTICAL")
    sys.exit(0)

print(f"{len(bad)} (op, ftz) pairs differ out of {len(OPS)*2}:")
print()
for (op,ftz),diffs in bad.items():
    print(f"  {op:<16} ftz={ftz}   {len(diffs)}/{nvec*4} lanes differ")
    for (v,l,x,y) in diffs[:4]:
        fx = struct.unpack("<f",struct.pack("<I",x))[0]
        fy = struct.unpack("<f",struct.pack("<I",y))[0]
        ulp = abs(x-y)
        print(f"      vec{v:>3} lane{l}: cpp=0x{x:08X} ({fx!r})  rust=0x{y:08X} ({fy!r})  bitdiff={ulp}")
    print()

ok = [o for o in OPS if all((o,f) not in bad for f in range(2))]
print(f"=== bit-identical ops: {len(ok)}/{len(OPS)} ===")
print("   " + " ".join(ok))
