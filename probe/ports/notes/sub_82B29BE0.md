# sub_82B29BE0

Non-leaf, 388 lifted lines, 227,982 calls on the boot session, `RwAudioCore Dac`. Census gate-1
verdict: pass, closure of 17, nothing outside it but `82F4DED0`/`82F4DFB0` (sin/cos). Mask
`kReturnR3`: `li r3,1` on every path.

Arguments: r3 = the mixer-side source object, r4 = the two-entry descriptor pair sub_82B34E08 also
swaps, r5 = a flag byte (only bit 0..7 are tested) choosing the hard mix over the ramped one.

Object layout, all plain offsets (nothing in `docs/rw_audio_structs.h` names this structure) and all
three regions contiguous: `+128` the config handed to sub_82B460A0 (its `+172..+184` are the four
channel-index words its callees place gains by, so self+300..+312); `+316` eight 16-byte panner
entries; `+444` the f32[8][8] gain matrix (row = source, column = destination), which ends exactly
at `+700`; `+700` the single stfs'd from `+100`; `+704..+740` the ten cached parameters; `+744` a
single handed to sub_82B460A0 in f4; `+748` source channels; `+752` destination channels.

Behaviour: load the ten live parameters from `+52` stepping by 8 (`+52 .. +124`) and compare each
with its cache at `+704 + 4i`, short-circuiting. (a) All ten equal: recompute the panner
(sub_82B45C50) and the matrix (sub_82B460A0) only if the flag byte is non-zero, then always
sub_82B29AF0 -- and cache nothing. (b) Any one moved: store `+700`, copy the matrix as it stands
into the frame at r1+96 (32 bytes per source row, seven `lfs`/`stfs` then one `lfsu`/`stfsu`),
recompute the panner and the matrix, then sub_82B29AF0 when the flag is set or sub_82B298E0 with the
saved matrix at r1+96 when it is clear, then publish all ten parameters into the cache. Both paths
end by swapping `+28`/`+32` on the pair, both words **reloaded** there rather than reusing the entry
copies, and return 1.

`sub_82B460A0` takes the matrix in **r10**, not a positional argument (`mr r27,r10` at its entry).
GuestCall stops at r3..r10 positionally, so r10 is set directly before the call; r6-r9 are left
alone because that callee never reads them, and neither does sub_82B45C50 (checked: it touches no
GPR above r4).

Stores: `+700` (4) and `+704..+743` (40) here; the two pair words (8); through sub_82B45C50 at most
panner entries 0..6, 16 bytes each -- its seven live cases are count 1 {0}, 2 {0,1}, 4 {0,1,2,3},
6 {0..4}, 8 {0..6}, and counts 3, 5, 7 store nothing at all, so `[+316, +428)` bounds it; through
sub_82B460A0 only inside `[+444, +700)`; through sub_82B29AF0 (sub_82B3BED8/sub_82B44B20) exactly
`[dst, dst+1024)` per destination channel, or through sub_82B298E0 (sub_82B3C098/sub_82B44D18)
`[dst & ~127, (dst & ~15) + 1024)` -- the dcbzl block is why the wider form is declared. The frame
copy at r1+96 and sub_82B298E0's per-row deltas at its own r1+80 are each their function's own
frame: not reproduced as windows, but r1 **is** lowered by 496 in the body, because without the
frame sub_82B298E0's 432-byte frame would sit on top of the buffer it is handed.

Window: one 428-byte span `[+316, +744)` (the union of all three object regions, a byte not written
compares equal anyway), the 8 pair bytes, and the destination channels merged where they abut.
Returns false when either count or any of the four channel-index words exceeds 8 -- the matrix is
8x8 and a larger value puts a callee's store outside it, where these windows do not follow -- and
when a channel run overlaps a control word that is re-read during the call (both counts, the four
index words, `+744`, both descriptors' base and stride). Live budget: 428 + 8 + at most 8 x 1136
bytes, 10 spans.

Unsure of: nothing in the body. The gate-2 guards are the honest edge -- eight is the matrix's own
dimension, not a measured bound on `+748`/`+752`, so a session that ever carries a ninth channel
will show up as skipped calls rather than as a divergence. `+700` versus the ten cached singles is
also unexplained: it holds the same parameter as cache slot 6 (`+100`) but is written only on the
recompute path and never read here.
