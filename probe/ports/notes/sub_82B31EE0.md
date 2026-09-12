# sub_82B31EE0

- Role: `void pump(stream* r3)` — one service pass over a stream's segment ring. In order:
  1. `u8[u32[object+12] + 71] == 2` parks the whole call;
  2. `sub_82B32480(object)`, unconditionally;
  3. retire: while `u8[slot(u8[object+468]) + 46] == 4`, call `sub_82B33F98(object, u8[+468])` and
     step `+468` on through the ring;
  4. take the slot at `u8[object+469]`. If its state byte is 0 or 4 — nothing in flight — refresh
     `f32[+424]` from `u32[+440]` when `u32[u32[+444]] == 0`, copy `+424` into `f32[+52]`, put
     **0x7FF7FFF1** in `u32[+48]`, put the pool double at 0x822F8700 in both `f64[+64]` and
     `f64[+56]`, and return;
  5. otherwise publish the same rate and sentinel, and set `f64[+64] = (double)(int32)[+436] /
     (double)f32[+428]`, `f64[+56]` likewise from `[+432]`;
  6. if that slot's `u32[+20]` is zero, step forward until a slot has work, the ring closes back on
     `+469`, or a slot reads inactive;
  7. then loop: for each active slot, copy `f32[owner+56]` into `f32[u32[record+36] + 8]`; state 1
     runs `sub_82B33D40` and becomes 2 (and, for `u8[record+72] == 3` on the first-active slot with
     an untouched timestamp, seeds `f64[slot+0]` from the clock plus the pool double at 0x822F9660);
     state 2 dispatches on `u32[record+20]` against the slot's `+24` then `+20` —
     `sub_82B33870`, `sub_82B33970` (whose out byte promotes the slot to 3), or
     `sub_82B332D0(...,0,0)`. Any callee returning a zero low byte ends the call. The loop stops when
     the shared counter at frame+88 passes **8192**.
  608 lifted lines, six direct callees, no indirect calls of its own, no imports, no timebase.
  206,045 boot calls on `RwAudioCore Dac` (tier D).
- Ring geometry: slots are **48 bytes**, at `object + u16[object+464] + 48*index` — the ring lives
  *inside* the object. `u8[+468]` is the retire index, `u8[+469]` the index the walk starts from and
  stops at, `u8[+470]` the wrap limit. A parallel array of **80-byte** records sits at
  `u32[object+96] + 80*index`. All three strides come from `rotlwi`/`rlwinm` chains, reproduced in
  `SlotAt()` and `RecordAt()` with the mnemonics quoted; the three different spellings of "double the
  index" (`rotlwi ,1`, `rlwinm ,1,23,30`, `rlwinm ,1,0,30`) all agree for a byte-masked index.
- The ring step is branchless: `subfic`/`subfe` turn "the low word of `limit - (i+1)` is zero" into
  an all-ones-or-zero mask and the `and` applies it. `NextIndex()` is that, and the derivation is in
  its comment. It appears three times in the original, identically.
- Stores: `stb [+468]` 1 per retire; `stfs [+424]` 4; `stfs [+52]` 4; `stw [+48]` 4;
  `stfd [+64]` and `stfd [+56]` 8 each (both on the idle path and the in-flight path);
  `stfs [u32[record+36]+8]` 4 per loop pass; `stb [slot+46]` 1 (to 2, and to 3);
  `stfd [slot+0]` 8. Plus the `stwu` back chain, the `std`/`lwz` at frame+88 and the out byte at
  frame+80 — all this call's own frame, none of it a window. Frame+88 is reused: first as the
  int-to-double spill for the two `fcfid`s, then as the counter the three callees advance.
- `fdiv` at step 5 and the `fadd` in the timestamp seed are **double** operations, not `fdivs`/
  `fadds`; the rate copies are single round trips.
- Constants, each `((imm & 0xFFFF) << 16) + offset`: `lis -32208` + `-31232` gives the pool base
  **0x822F8600**, from which `+256` = **0x822F8700** (the idle/"untouched" double, loaded on both
  paths) and `+4192` = **0x822F9660** (the timestamp bump). `lis 32759` + `ori 65521` =
  **0x7FF7FFF1** for `u32[+48]`.
- Result: **none.** No `li r3,...` on any path — the function is void. r3 at exit is whatever the
  last call left, and on the idle path it is scratch from the retire loop's own index arithmetic
  (`add r3,r11,r10`), which the port does not reproduce because nothing can read it. The macro line
  still carries `kReturnR3`: a gate-labelled port with a false `Windows()` and `kReturnNone` trips
  lint check 5. The honest mask is `kReturnNone`.
- Gate 1 **fails at depth 2 and unavoidably**: `sub_82B32480` is called on **every** path and its
  only callee is `sub_82EC1378`, which is where the census places
  `RtlEnterCriticalSection`/`RtlLeaveCriticalSection`. `sub_82B33D40` reaches the same function, and
  `sub_82B33F98` has an indirect call of its own (census `indirect: 1`). The transitive closure is
  198 functions wide. `Windows()` returns false.
- Gate 2 would fail too, on the walk: which slots the loop touches, and therefore which `[slot+46]`
  and `[slot+0]` bytes are written, depends on what the callees do to the counter at frame+88 and to
  the state bytes during the call. The fixed part is enumerable — `{object+48,24}` (48, 52, 56, 64),
  `{object+424,4}`, `{object+468,1}` — but the per-slot part is not.
- Unsure: (a) whether `u8[+469]` is the write index or the oldest in-flight index. The retire loop
  advances `+468` and both walks start at `+469` and terminate when they come back to it, which
  reads as `+468` = the oldest slot and `+469` = the first one still to service, but nothing here
  proves it. (b) `+113` as reached through `16*u8[+473]` — the port calls it a selector flag because
  a nonzero value parks the walk at two separate places, but the array it indexes is not identified.
  (c) `u32[+444]`, whose *pointee* gates the rate refresh; only the dereference is certain.
