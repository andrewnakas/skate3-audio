# sub_82B43AF8 — a biquad over a run of singles, eight samples per pass

Arguments: r3 the four-single history `{x[k-1], x[k-2], y[k-1], y[k-2]}`, r4 the destination run,
r5 the source run, r6 five coefficients `{a1, a2, b0, b1, b2}`, r7 the sample count. Void: r3 is
left as it arrived on both paths, so the mask is `kReturnNone` and the comparison rests on the
windows. One callee, `sub_82B43978`, through `GuestCall`. 658,251 calls in a boot session, on
`RwAudioCore Dac`.

Recurrence, per sample: `t = x[k]*b0 + x[k-1]*b1 + x[k-2]*b2`, then `+ bias` (a rodata single at
kPool+432 = 0x822F87B0, the usual denormal floor), then `y = t - y[k-1]*a1 - y[k-2]*a2`. Each of
the five arithmetic steps rounds to single once; the two subtractions are `fnmsubs`, so they are
fused. The tap order is not uniform: samples 0 and 1 reach into the history and round their three
taps as (b0, b2, b1) and (b0, b1, b2), while samples 2..7 round as (b1, b2, b0). All eight are
verified against the register trace of the lifted body and are spelled out in the file, because
the orders are not interchangeable in floating point.

`r7 % 8 != 0` or `r7 == 0` tail-calls `sub_82B43978` with r3..r7 untouched — the generic form of
the same filter, four samples per pass plus a remainder loop. Its write set is identical: `[r4,
r4 + 4*r7)` plus the four history singles. That is why `Windows()` does not have to predict which
path runs.

Stores: `[r4 + 4k)` for k in [0, r7) and the four singles at r3+0/4/8/12. Nothing else. The
frames are excluded — the back chain at r1-192 here, `stfd f31,-8(r1)` inside the callee — but
Native still moves r1 down 192 bytes so the callee's spill lands where the original put it,
below this frame rather than on top of the caller's.

Window rationale: `span = (r7 << 2) & 0xFFFFFFFC`, exactly as `rlwinm r11,r7,2,0,29` computes it.
Two spans, `[r3, 16)` and `[r4, span)`. `Windows()` returns false when r3 or r6 is null (both are
dereferenced unconditionally), when r4 or r5 is null with a nonzero span, when `r4 + span` or
`r5 + span` wraps the address space (the loop's exit test is a pointer compare, so a wrapped run
either never terminates or writes a set no window describes), and when `span + 16` exceeds the
32 KB harness budget — over 8,190 samples in one call.

All eight inputs of a pass are read before any of its outputs are written, which is what makes an
in-place call (r4 == r5) work; the port keeps that split deliberately and does not fold the loads
into the per-sample loop.

Gates: 1 passes — `sub_82B43978` is a pure leaf: no call, no import, no indirect call, no lock,
no reservation (it is outside the audio corpus, so it has no census entry; its 237 lifted lines
were read in full). 2 passes, write set fully enumerable from r3/r4/r7. 3 passes, no `mftb`.
4: void, and the whole result is in the two windows.

Evidence: shadow-clean in `s23` — 522,870 runs at the last periodic report, `registers=0 memory=0
skipped=0 overflow=0`, against 773,174 census calls. `skipped=0` means `Windows()` returned true
every time, so no real call has a null r3/r6, a wrapped run, or a span over the budget. All four
entry dumps that session show `r7=00000100`, 256 samples, so the eight-at-a-time path is what is
being exercised; whether the `sub_82B43978` branch is ever taken is not established either way by
a clean session, since both paths are compared through the same windows.

Unsure: whether the coefficient block is really `{a1, a2, b0, b1, b2}` in the caller's own terms
or a different packing that happens to be used this way here; and whether `bias` is the same
denormal floor `sub_82B43978` reads at the identical pool offset (it is the same address, read
the same way, so the port treats it as one cell).
