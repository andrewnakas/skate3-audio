# sub_82B29AF0

Non-leaf, 143 lines, 125,476 calls in the verifying boot session on `RwAudioCore Dac` (153,104 in
the screening census). Compared clean, promoted to `kPortVerified`. This is the **channel mix
matrix**: two nested loops that call nothing but the two VMX128 gain kernels, both of which are
themselves verified ports.

Arguments: r3 = the mixer, r4 = the **destination** buffer descriptor, r5 = the **source** one.
The direction is not a guess -- `sub_82B3BED8`/`sub_82B44B20` take r3 = dst, r4 = src, r6 = count,
f1 = scale, and this function builds the kernel's r3 from r4's fields and its r4 from r5's.

Mixer fields (nothing in `docs/rw_audio_structs.h` names them): `f32[source][dest]` gain matrix at
`+444`, row stride 32 bytes (eight floats, so at most eight destinations per row);
`u32 +748` source channel count; `u32 +752` destination channel count. Descriptor fields, the same
in both: `u32 +4` channel 0's float array, `u16 +14` floats between channels.

Behaviour: pass 1 walks destinations `d = 0 .. [+752)` calling `sub_82B3BED8(dst_d, src_0, 256,
gain[0][d])`, which **overwrites** (`dst[k] = src[k] * gain`). Pass 2 walks sources
`s = 1 .. [+748)` and, inside each, destinations `d` again, calling `sub_82B44B20(dst_d, src_s,
256, gain[s][d])`, which **accumulates** (`dst[k] += src[k] * gain`). Overwrite-then-accumulate is
why source 0 gets a different kernel; a matrix mix needs no separate clear pass.

Callees, and how they are handled: both go through `GuestCall(ctx, base, sub_82B3BED8|sub_82B44B20,
dst, src, ctx.r5.u64, 256)`, never `__imp__`. r5 has to be passed because r6 is positional; the
original leaves whatever the previous call put in r5 and both kernels write r5 before reading it, so
`ctx.r5.u64` reproduces that chain exactly. Both are leaves: no indirect call, no lock, no
allocation, no `mftb`, census gate-1 verdict pass, closure size 2. Their entire write set is
`[r3, r3 + 4*r6)` -- confirmed both from their store provenance (the `dcbzl` is only reached when
both pointers are 128-byte aligned, where `r11 & ~127 == r11`) and from their own ported
`Windows()`, which declare exactly that span.

The gain cursor: `addi r29,r3,440` plus `lfsu`'s `+4` pre-increment is what puts gain[0][0] at
`+444`; pass 2 uses `addi r24,r28,476` with `addi r29,r24,-4`, and `addi r24,r24,32` per source,
which is the row stride.

`r11` is one variable across both passes, deliberately. It holds `[+752]`, is reloaded after every
kernel call, and the second pass's `cmplwi cr6,r11,0` tests whatever the LAST reload left -- not a
fresh read. If the first pass never ran (count 0 at entry) it is still 0 there, and the inner loop
stays skipped for every source. Modelling that as two variables would be wrong.

Both hard-won 64-bit rules apply to the address arithmetic and the port keeps them:
`mullw r9,r11,r31` is a 64-bit product of two sign-extended words; `rlwinm rX,rX,2,0,29` is a
32-bit shift left by two (the rotate's wrapped bits are masked off); `add r3,r11,r10` sums two
zero-extended words in 64 bits, so a channel address can carry into bit 32 and only the callee's
address truncation drops it. `ChannelAddress()` is `uint64_t` end to end.

Own frame: `stwu r1,-160(r1)` **is** reproduced, unlike most ports. Both kernels spill f1 and their
callee-saved registers below the live r1 and read that scratch back (`stfs f1,-32(r1)` then
`lvx128 v63,r0,r30` with r30 = r1-32, and `stfs f1,-48(r1)` then `lvx128 v0,r0,r9` with r9 = r1-48);
without the frame that lands 160 bytes higher than the original put it. It is still not windowed:
it is this function's own frame, every access in it is write-before-read, and the back-chain word
the port stores is the same value the lifted `stwu` stored. r1 is restored exactly. The
`__savegprlr_24` spill is not reproduced -- the port touches no callee-saved register.

Stores: none of its own. The whole write set is the destination channels, `4*256 = 1024` bytes
each, `[+752]` of them. Pass 2 reuses the same destinations pass 1 walked, so one sweep names all of
it. Contiguous or overlapping channels are merged into one span, which is what keeps an interleaved
destination buffer inside the 32-span budget.

Window, and why the alias check is load-bearing rather than paranoia: four words drive the
iteration counts and the addresses and **all four are re-read during the call** -- `+748`, `+752`,
and both descriptors' `+4`/`+14`. If a kernel's output covered any of them, the loop bound could
grow mid-call and a later iteration would write outside the declared set. So `Windows()` checks
every declared channel span against `{mixer+748, 8}`, `{dst_desc+4, 12}` and `{src_desc+4, 12}` and
returns false on any overlap. It also returns false when `[+752] > 32` (32 channels of 1024 bytes is
exactly `kPortWatchCap`, so nothing wider could be compared in any case) and when a channel span
would wrap 2^32.

Reads are recorded for replay only: the two counts, the gain matrix from row 0 column 0 to the last
row's last column, both 16-byte descriptors, the destination spans (`sub_82B44B20` reads its
accumulator before writing it), and the source channels summarised by one span over the extremes
rather than one per channel, to stay inside the 32-span input table.

Gates: 1 pass. 2 pass conditionally, per the three exits above; the census reported
`gate2_suspect: 0` and `stores_present: false` because the function's only own store is its frame.
3 pass. 4 pass -- `kReturnNone`: both call sites (`skate3_recomp.67.cpp:29448` and `:29585`) branch
away immediately without reading a register, so naming any result would only invite a false
divergence.

Unsure: (a) with `[+752] == 0` the call writes nothing and `kReturnNone` names nothing, so such a
call compares only r1 and the callee-saved set -- a near-vacuous green. It is the honest answer (the
original does nothing observable either), but a census showing mostly zero-destination calls would
make the verified count worth discounting. (b) The alias check assumes only this call can write the
four control words; another thread writing `+752` mid-call is a real race the harness cannot model
and which would hit the lifted run identically. (c) Field names are read off the arithmetic; no
symbol names the mixer or the descriptors.
