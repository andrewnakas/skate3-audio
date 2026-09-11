# Bug 3: the negative buffer size — root cause

`skate3_audio_fixes.cpp` hooks `sub_82B7F828` and clamps a negative size, noting that
"whoever *computes* `-12` is still unknown". Reading the decompiled code identifies the
defect.

First, a correction: `sub_82B7F828` is **not** an allocator and does no clamping of its own
(the clamp is in the recomp's hook). It initialises a **pair of ring-buffer descriptors**
from two `{pointer, size}` arguments and zeroes each region:

```c
param_1[0] = bufA;  param_1[2] = sizeA;  ...  if (bufA) memset(bufA, 0, sizeA);
param_1[5] = bufB;  param_1[7] = sizeB;  ...  if (bufB) memset(bufB, 0, sizeB);
```

`sub_82F52040` is `memset`, and it is the call that receives `-12`. So the naming in
`out/names.csv` is now `rwaudio_InitBufferPair` / `rwaudio_MeasureBufferPair`.

## The measure/allocate split

`sub_82B7F998` is a **bounds-checked bump allocator**. It advances a running offset,
records a high-water mark, and hands back a pointer only when the accumulated size still
fits the capacity — otherwise NULL:

```c
*(uint *)(p + 0x18) = used + 0x24;                       // advance
if (*(uint *)(p + 0x20) < used + 0x24)                   // track peak
    *(uint *)(p + 0x20) = used + 0x24;
ptr = -(uint)(used + 0x24 <= *(uint *)(p + 0x1c))        // NULL unless it fits
      & (*(int *)(p + 0x14) + used);
```

It fills two descriptors, each laid out `{ptr, offset, capacity, peak, status}` — the
caller reads `peak` as the required size and `status` as the result code. Running it with
zero capacity measures; running it again with real capacity allocates.

## The defect

The caller, `sub_82B7F8A8`, validates the wrong things:

```c
sub_82B7F998(obj, &desc);
sizeA = desc.a.peak;  sizeB = desc.b.peak;
if ((-1 < (int)desc.a.status) && (-1 < (int)desc.b.status)) {     // (1)
    if (avail != 0) {
        if (avail < (uint)(sizeB + sizeA)) return E_OUTOFMEMORY;  // (2)
        rwaudio_InitBufferPair(out, base, sizeB, base + off, sizeA);   // memsets both
```

1. The non-negativity test is applied to the two **status** words, not to the sizes.
2. The only size validation is on their **sum**, and it is an **unsigned** comparison.

So a negative individual size is never rejected. If one peak is negative and the other
positive enough that the sum stays small and positive — say `sizeA = -12`, `sizeB = 1000`,
sum `988` — check (2) passes, and both sizes are then handed to `InitBufferPair`, which
calls `memset(bufA, 0, -12)`. As a `size_t` that is 0xFFFFFFF4, which is the reported
4 GB walk and the `0x70000000` fault on the render thread.

If *both* were negative the sum would wrap to a huge unsigned value and (2) would catch it.
That is why this manifests rarely and looks non-deterministic: it needs exactly one
negative component, masked by a positive one.

## The fix

Validate each size independently before use, rather than their sum:

```c
if ((int)sizeA < 0 || (int)sizeB < 0) return E_INVALIDARG;
if (avail < (uint64_t)sizeA + (uint64_t)sizeB) return E_OUTOFMEMORY;
```

Widening the sum to 64 bits also removes the overflow path in (2). This is a strict
improvement on the current mitigation, which clamps the size at the memset and so silently
produces a zero-length buffer that the caller still believes is valid.

## Still open

*Why* a peak goes negative is not established — it comes out of the accumulation in
`sub_82B7F998`, and reaching a negative requires either a bogus element count or an
overflow upstream. Pinning that down needs a reproduction, and the fault is reported only
on QCS8550 handhelds, so it is blocked on hardware in the same way the `0x8210A310`
corruption is. The validation fix above is correct and worth making regardless, because it
converts a wild 4 GB memset into a clean error return at the point the bad value is first
observable.
