# sub_82B3DEA8

Non-leaf, 132 lines, 266,878 calls in the promoting session (the package said 330,526 for an
earlier boot), all on `RwAudioCore Dac`. Shadow-verified clean and promoted.
No stores of its own outside its frame: everything it writes, it writes through memcpy.

The same family as `sub_82B3DD90`, `sub_82B3DC48`, `sub_82B3DB90` and `sub_82B3DF90` -- all
five take the same stream object in r3 and all five are called 330,526 times a boot from the
same caller (`sub_82B3D8xx`, one call each per block). The shared object fields used here:
`+0` float-ring byte base, `+20` span-high, `+24` span-low (the ring holds `+20` words and
`+24` is the lag), `+52` the running word position. `sub_82B3DB90.inc` already names `+20`
`kSpanHigh` and `+24` `kSpanLow`; `sub_82B3DF90.inc` names `+16` `kBlock` and `+20` `kEnd`.
The three new files use one set of names across all of them.

Args: r3 = stream object, r4 = block index, r5 = words in the block, r6 = the caller's output
record (at the caller's frame + 80), whose `+16` is one past the last word produced --
`sub_82B3DD90` writes that field from `sub_82B3DC48`'s return and the caller advances it per
block. This function is the write-back half: it copies the block that was just produced back
into the ring.

Body: `ring_start = [obj+0] + 4*([obj+20] * r4)`, `ring_end = ring_start + 4*[obj+20]`, and
`cursor = ring_start + 4*(([obj+52] mod [obj+20]) + [obj+24])`. If the cursor is below
`ring_start` or at/past `ring_end` it gets `4*([obj+20] - [obj+24])` added (the same wrap
normalisation `sub_82B3DB90` performs inline). `source = [r6+16] - 4*r5`. A block at least as
long as the ring (`r5 >= (ring_end - ring_start) >> 2`) returns immediately having written
nothing. Otherwise `run = min(r5, (ring_end - cursor) >> 2)` and
`memcpy(cursor, source, 4*run)` then `memcpy(ring_start, source + 4*run, 4*(r5 - run))`. Two
`tw` guards, `twllei r3,0` on the span and `twlgei r8,-1` on the divide, are reproduced;
`ppc_trap(type 0)` only warns and returns, so both are comparable rather than fatal.

Stores: none directly. Through `sub_82EDF460`: `{cursor, 4*run}` and
`{ring_start, 4*(r5-run)}`.

Callee: `sub_82EDF460`, the XDK vector memcpy, through `GuestCall`. It writes exactly
`[r3, r3+r5)` on every path (its `dcbzl` lines are rounded up into the destination and then
fully overwritten; its spills sit below its own r1). No locks, no allocation, no indirect
calls -- the census transitive gate 1 over the closure {82EDF460, 82EE7460, 82F52FB8} is pass.

Windows: the two destination runs. Every load in the original happens before the first copy,
and the second copy's arguments come from non-volatile registers rather than a reload, so the
whole plan is fixed at entry -- `MakePlan()` is shared by the body and the window builder so
the two cannot drift. Refuses when the two lengths together exceed the 32 KB cap (which is
also what catches a negative run, since `rlwinm` turns it into a ~4 GB length), when a span
would wrap 2^32, or when a non-empty run starts at guest address 0.

Gates: 1 pass, 2 pass, 3 pass (no timebase), 4 pass.

Result mask `kReturnR3`, deliberately, even though the caller ignores r3 (it goes straight to
`cmpwi cr6,r30,256`). r3 is `cursor` on the no-copy path and `ring_start` on the copy path
(memcpy returns its own destination), both reproduced exactly -- and the no-copy path has no
stores, so without r3 it would compare nothing at all. It verified clean with the mask on, so
the extra check cost nothing; if it ever diverges in r3 alone with clean windows, drop the mask
to `kReturnNone` rather than hunting a bug -- it is not a real caller-visible result.

Widths that matter: both `mullw`s keep the full 64-bit product, and `add r31,r10,r9` /
`add r10,r10,r31` / `subf r27,r5,r6` are 64-bit on zero-extended words, so a carry into bit 32
survives into the value the callee receives and only truncates at the compares and the stores.

Unsure: `+20` and `+24` are read as word counts because their difference is scaled by four
before being added to a byte address; nothing documents either. Verification says the paths the
session took agree; it does not say which paths those were, so the `bge` early return (a block
at least as long as the ring) and the wrap-adjust branch may or may not have been exercised
inside those 266,878 calls. The window builder's five refusals are all unreached in practice
(they would each mean the original itself handing memcpy a ~4 GB length).
