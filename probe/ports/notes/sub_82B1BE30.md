# sub_82B1BE30

- Role: `? f(object*, int id, int value)` — a clamp-and-dispatch property setter. It validates the
  id, clamps the value to the range that id uses, and **tail-branches** into the object's own
  setter through its vtable. 179 lifted lines, no direct callees, no imports, no stores at all, no
  timebase, no lock; six `bctr` sites. 12,461 boot calls on `RwAudioCore Dac` (tier D) — one of the
  hottest functions in the corpus, which fits a generic "set property" entry point.
- Arguments: r3 = object (vtable at `+0`), r4 = property id, r5 = value. r6-r10 are not read.
- Control flow, in full:
  - `r3 == 0` (`cmplwi`/`beqlr`): return immediately, r3 left at 0.
  - `r4.u32 > 8` (`cmplwi`, **unsigned**, so a negative id comes here too) → `loc_82B1BF3C`, which
    then tests `r4.s32 < 9` and `r4.s32 > 136` **signed** and returns on either. So ids 9..136 are
    accepted and dispatched with **no clamp**; a negative id falls out at the `bltlr`.
  - ids 0..8 select through `mtctr r4` + seven `bdzf 4*cr6+eq` + a trailing `bne cr6`. cr6+eq is
    `r4 == 0` and nothing reassigns cr6, so the n-th `bdzf` fires exactly when the id is n; id 8
    exhausts all seven and the `bne` catches it; id 0 keeps eq set, nothing branches, and control
    falls through the chain into the code at the bottom of the entry block. The port derives the
    same index by running the same seven decrements against `ctx.ctr.u32`; because only the low 32
    bits decide, that is equivalent for any 64-bit r4, including one with a nonzero high half.
    CTR itself is dead after the chain — every path reloads it with `mtctr r9`.
- The clamp per id, and the slot:
  | id | clamp | argument shape | slot |
  |---|---|---|---|
  | 0 | `[0, 65535]` signed | `r4 = 0` (redundant `li`), `r5 = clamped` | `+12` |
  | 1, 4 | none | `r5 = value` | `+12` |
  | 2, 5, 8 | `[0, 32767]` signed | `r5 = clamped` | `+12` |
  | 3 | none | `r4 = value`, `r5 = 0` | **`+16`** |
  | 6, 7 | `[0, 65535]` signed | `r5 = clamped` | `+12` |
  | 9..136 | none | `r5 = value` | `+12` |
  Both clamps compare **signed** (`cmpwi r11,0` then `cmpwi r11,32767` / `cmpw r11,r10` where
  r10 = `lis 0`+`ori 65535` = 65535), so a negative value becomes 0, never a large unsigned one.
  Ids 0, 6 and 7 are byte-identical code at two different labels; id 3 is the only one that moves
  the value into r4, zeroes r5 and uses the second vtable slot, which reads like a different
  setter signature (one argument rather than an id/value pair).
- Stores: **none.** Not one store in 179 lines; the only memory access is `lwz r10,0(r3)` and
  `lwz r9,{12,16}(r10)` at each dispatch site.
- Result: whatever the vtable setter returns. All six dispatches are `bctr`, **not** `bctrl` — lr
  is untouched, so the setter returns directly to this function's caller. The port therefore does
  not write `ctx.lr`, and does not rewrite `ctx.r3` either (the object is already there, so the
  callee sees the entry register bit for bit).
- Gate 1 **fails** at depth 0: every path that does anything at all ends in an indirect branch
  through `u32[u32[r3] + 12]` or `+16`. The census agrees (`verdict: fail, reason: indirect, depth
  0`, `indirect: 6`). `Windows()` returns false — and there is nothing else it could say, since
  this function's entire write set is the callee's.
- The macro line carries `kReturnR3` although the honest mask is **`kReturnR3` as well**: the tail
  callee's return value *is* this function's, so r3 is genuinely the result register. (The three
  early-return paths leave r3 at its entry value — 0, or the object for an out-of-range id — which
  a caller reading r3 would see as garbage, so no caller can plausibly read it on those paths.)
- Unsure: what the ids mean. No plug-in metadata names them and there are no strings on these
  paths, so the reading "property id" comes only from the shape (dense small ids, per-id clamp,
  vtable dispatch). The `[9,136]` window is oddly wide and unclamped; whether 136 is a real last
  id or the end of a second table nobody indexes here is unknown. `+12`/`+16` were not
  cross-checked against another vtable user.
