# sub_82B3D4F8 — mix dispatcher over a six-pointer buffer descriptor

Lifted: `skate3_recomp.68.cpp:9763`, 76 lines. Thread `RwAudioCore Dac`, boot 174,693 calls.
Void; no stores of its own outside its frame. Two callees, both leaf VMX kernels:
`sub_82B3CF58` (one gain) and `sub_82B3D0A8` (two gains).

## Arguments

- `r3` gain block: `+16` and `+20` singles (`sub_82B39FA0` reads the same object at `+16..+32`).
- `r4` sample count, passed to either kernel in `r3` — and left in `r4` as well, because the
  original never reassigns it. Neither kernel reads `r4` on entry.
- `r7` descriptor: `+0` addend (y), `+4` source (x), `+8` selector, `+12` extra, `+16` mixed
  output (z), `+20` copy output (w). The last two are the only ones written, on **either** path;
  `+8` and `+12` turned out to be arrays too, not scalars — see Resolved.

## Paths

`selector == 0`: `sub_82B3CF58(n=r4, y=desc[0], x=desc[4], z=desc[16], w=desc[20], f1=gain0)`.
Writes z and w, four bytes per sample each.

`selector != 0`: `sub_82B3D0A8(n=r4, r5=desc[20], r6=desc[0], r7=desc[4], r8=selector,
r9=desc[12], r10=desc[16], stack 84(r1)=desc[20], f1=gain0, f2=gain1)`. The stack argument is
real: `sub_82B3D0A8` opens with `lwz r30,84(r1)` and never does its own `stwu`, so it reads the
slot out of this function's frame. `desc[20]` therefore goes across twice, in `r5` and on the
stack; reproduced, not tidied.

## The frame is reproduced, deliberately

`stw r12,-8(r1)` (frame + 88) and `stwu r1,-96(r1)` (the back chain) are this call's own frame
and are not windowed, but the frame has to exist: it carries `84(r1)`, and `sub_82B3CF58` also
writes its gain splat at `r1-128..r1-113` relative to the `r1` it is handed. `r1` is set to
`entry - 96` before either call and restored with `addi r1,r1,96` after, then `lr` is reloaded
from the slot exactly as the epilogue does.

## Windows

**Both paths are enumerated (changed 2026-09-12).** They write the same two buffers, so there is
one enumeration with one branch in it.

- `selector == 0` returns true: two write spans for the vector body (`z` and `w` from their
  16-byte floor, `64 * (n/16)` bytes, only when `x` is 16-byte aligned) and two for the scalar
  tail (`4 * (n - 16*(n/16))` bytes at the exact base). Copied from `sub_82B3CF58`'s port, whose
  derivation of the `stvx128` address masking distributing out of the loop is the load-bearing
  part.
- `selector != 0` used to return **false**, on the grounds that `sub_82B3D0A8` is "662 lines with
  eight `stvx128` and nine `stfsx` into six buffers, every base a loop cursor plus an inter-buffer
  delta computed inside the call". All of that is true and none of it matters: **the deltas
  cancel**. Every one of those store addresses is a cursor into one array plus the precomputed
  difference to another, so `stvx128 v39,r27,r11` is `(desc[20] - desc[4]) + (desc[4] + 32 + 64k)`
  = `desc[20] + 32 + 64k`. Resolve all eighteen (8 `stvx128`, 1 `stfs`, 9 `stfsx`) and only
  **two** arrays are ever written: `desc[16]` and `desc[20]` — the same `z` and `w` the one-gain
  kernel writes, with the same geometry (64 bytes per 16-sample block from the 16-byte floor, then
  four bytes per sample at the exact base). The other four are read. Nothing else leaves its
  frames: the rest of its census entries are `20(r1)` and `-164(r1)` through `-224(r1)`. Several
  store bases *are* loaded from memory, but every one of those loads is a spill of an argument
  register out of its own frame (`-208(r1)`, `-216(r1)`, `-224(r1)`, `20(r1)`); the only loaded
  address that is not is `84(r1)` — the ninth-argument slot **this** function stores, from
  `desc[20]`, before the call.
- The only difference is the vector gate: `sub_82B3CF58` needs its source 16-byte aligned,
  `sub_82B3D0A8` needs `desc[4]` **and** `desc[8]` aligned. A failed gate only moves samples from
  the vector spans into the scalar ones, so the same four spans cover both, and the port computes
  `blocks` with both conditions.
- `n <= 0` returns true with no spans: both kernels' `bge` leaves before any store. (In
  `sub_82B3D0A8` that is `done >= count` at `loc_82B3D2A4`, where `done = 16*trunc(n/16) >= n` for
  every `n <= 0`.) Such a call compares only the ABI-preserved registers — vacuous, but not wrong,
  and the same hole exists in `sub_82B3CF58`'s own port.

Derived from the lifted body twice over: a flow-sensitive provenance pass over every store, and
the store table in `sub_82B3D0A8.md`, written independently, which lists exactly `E` = `desc[16]`
and `F` = `desc[20]`. It does **not** rest on `sub_82B3D0A8`'s port being green — that note says
it has never been compared.

**What it was costing.** In `probe/harness/out/s20.log`, `sub_82B3D4F8 skipped=46,957` against
`sub_82B3D0A8 calls=46,957` at the same report — equal to the digit, so every skip was a two-gain
call and every two-gain call was a skip. That is **34% of 138,385 calls**, and `sub_82B3D0A8` is
called from nowhere else, so the harness was watching this dispatcher decide between two kernels
while only ever seeing one of them chosen. After the change every call with `n > 0` inside the
32 KB budget is comparable, so expect `skipped` **0**; at the observed `n = 256` the four spans
total 2 KB, nowhere near the budget.

## Gates

Gate 1 pass (both callees are leaves: no lock, allocation, import, indirect call or timebase).
Gate 2 now passes on both paths, as above. Gate 3 pass. Gate 4: void, so the mask is
`kReturnNone`; `r3` after the call holds whatever the kernel left, produced by the same code in
both runs, so nothing is gained by comparing it.

**STATUS is `verified`, and that label predates this change**: it was earned on a session that
never once compared the two-gain path. Re-earn it on one session with this enumeration before
anything is promoted on it.

## Resolved

- **`desc[8]` is a pointer, not a mode.** `sub_82B3D0A8` alignment-tests it (`clrlwi r11,r8,28`)
  and reads it as the second source array, so the dispatch really means "is there a second
  source": `desc[8] == 0` picks the one-gain kernel because there is nothing to cross-fade with.
- **`desc[12]` is the per-sample cross-fade coefficient array** — `sub_82B3D0A8`'s `D`, read only.
  With `desc[0]` = `A` (accumulator), `desc[4]` = `B`, `desc[8]` = `C`, `desc[16]` = `E` and
  `desc[20]` = `F`, the descriptor is six float arrays and `sub_82B3D0A8.md`'s per-element
  formulas apply verbatim.
