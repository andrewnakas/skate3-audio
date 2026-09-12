# sub_82B3CF58

Leaf kernel, 218 lines, 25 vector instructions, **98,811 calls per boot session**, first called
on `RwAudioCore Dac`. No callees, no imports, no indirect calls, no timebase, no locks.
**STATUS verified**: promoted by the session that followed this port, with no divergence recorded
(`probe/ports/queue.json`, `last_divergence: null`).

Scale-and-add with a parallel copy of the source. For `n = r3` samples:
`z[i] = x[i]*gain + y[i]`, then `w[i] = x[i]` — where the copy **reloads** x after the z store,
so an in-place call (`z == x`) copies the scaled result rather than the original. That is
reproduced, not fixed. Arguments: r3 = n, r5 = y, r6 = x, r7 = z, r8 = w, f1 = gain. r4 is not
an input.

Two paths, chosen on `r6 & 0xF`:

- x 16-byte aligned: a vector body of `blocks = n/16` iterations, 64 bytes per buffer per
  iteration (four `vmaddfp`, four `stvx128` to z, four reloads of x, four `stvx128` to w), then
  the scalar tail over `n - 16*blocks` samples.
- x unaligned: the scalar tail over all n samples, `fmadds` per sample.

**Stores.** Vector path: `(z + 64k + {0,16,32,48}) & ~0xF` and `(w + 64k + {0,16,32,48}) & ~0xF`,
16 bytes each, k in [0, blocks). Scalar tail: `z + 4i` and `w + 4i`, 4 bytes each. The four
`stfs f1,-128(r1)..-116(r1)` that build the gain splat are the function's own frame and are not
windowed (the brief's exemption); they are reproduced anyway so the `lvx128` that reads them back
sees the same bytes.

**Windows: enumerable, returns true on every path.** Every effective address reduces to one of
the four bases plus a multiple of 16, so `(A + 16m) & ~0xF == (A & ~0xF) + 16m` and each buffer's
vector traffic collapses to one contiguous run from the 16-byte floor of its base. Both trip
counts are closed forms of r3 (`n/16`, then `n - 16*(n/16)`), so four write spans at most.
Unaligned z or w writes *below* the base, not above — the window starts at the floor for that
reason. A negative or zero n stores nothing: the `bge` at loc_82B3D05C is a signed word compare
and `16*(n/16) >= n` holds for every n <= 0. The only `return false` is an overflow guard at
2^24 samples, far above the harness's own 32 KB budget (8 bytes written per sample).

**Gates.** 1 pass (leaf), 2 pass, 3 pass (no timebase), 4 pass (the stores are the result).
Mask `kReturnNone`: the function is void, leaves r3 untouched, and clobbers nothing the ABI
preserves — r20-r31 come back through `__restgprlr_20`, and the vector registers it uses (v0,
v10-v13, v60-v63) are all volatile.

**Unsure of:** whether real callers ever pass an unaligned x. 25 vector instructions and ~99k
calls suggest the vector path is the normal one, so a session that only ever exercises it leaves
the scalar tail thin even at zero divergence — the same "well exercised except one path" caveat
`CLAUDE.md` records for `sub_82B28A00`. Worth reading the divergence counters against the
`blocks == 0` case specifically.
