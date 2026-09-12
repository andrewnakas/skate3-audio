# sub_82B3DD90

Non-leaf, 155 lines, 330,526 calls in the boot session, all on `RwAudioCore Dac`.
**Gate 2: the write set is not enumerable from entry state.** The body is written and exact; it
is the reference for the Rust port and for anyone reading the family.

The hub of the family. Called once per block by `sub_82B3D8xx`, it builds the two structures the
rest of the family consumes, hands them to `sub_82B3DC48`, publishes the results in the caller's
record, and lets `sub_82B3DF90` zero what the fill did not reach. `sub_82B3DEA8` is then the
write-back half, called by the same caller from the same record. All five share the stream
object in r3, and `sub_82B3DB90.inc` / `sub_82B3DF90.inc` already name most of its cells; the
three new files use one name set across all of them.

Args: r3 = stream object, r4 = block index, r5 = words consumed so far in this block, r6 = the
caller's output record (caller frame + 80). Returns 256, a constant, which the caller does read.

Object fields: `+0` float-ring byte base, `+16` block (the cap base), `+20` span-high, `+24`
span-low, `+40`/`+44` the two segments' word counts, `+52` the running word position, `+56` a
u8 flag meaning "two segments".

Body. It builds, on its own frame, a 16-byte ring window at `+80` and a 32-byte segment array at
`+96`:

- window `+0` = `[obj+0] + 4*([obj+20] * r4)`, `+4` = that plus `4*[obj+20]`,
  `+12` = `+0` plus `4*((([obj+52] + r5) mod [obj+20]) + [obj+24])`, `+8` = `+4` less
  `4*[obj+24]` (stored, and read by nothing in this family).
- segment 0: need = `[obj+40]`, cap = `[obj+16] + 255`, out = 0. With `[obj+56]` non-zero,
  segment 1: need = `[obj+44]`, cap = `[obj+16] + 127`, out = 0, and the segment count becomes 2
  instead of 1.

Then `sub_82B3DC48(obj, window, segments, count)`; its return goes to `out+16`, segment 0's out
pointer to `out+4`, and segment 1's out pointer to `out+8` -- the last masked by a
`subfic`/`subfe`/`and` built from a **re-read** of `[obj+56]`, so it publishes zero when the flag
is clear. That mask is load-bearing, not decoration: `segments+28` is only initialised on the
flag's own path, so without it the call would publish stack garbage. (`subfe r6,r7,r7` uses the
r7 `sub_82B3DC48` left behind, but `~r7 + r7` is all ones whatever it holds, so only the carry
matters.) Finally `sub_82B3DF90(obj, r5, out)` and `r3 = 256`.

Unlike most ports this body has to build its frame (`stwu r1,-176(r1)`, restored before
returning): the window and the segment array live in it and their addresses are passed to
`sub_82B3DC48`, so they need real guest memory at the same addresses. Those bytes are the
function's own frame, below the caller's r1, which the brief excludes from the windows -- the
original writes exactly the same cells.

Stores outside the frame: `{out+4, 4}`, `{out+8, 4}`, `{out+16, 4}`, plus everything the three
callees write.

Callees, all through `GuestCall`: `sub_82B3DC48` (ported, verified) and `sub_82B3DF90` (ported,
verified), reaching `sub_82B3DB90` (ported) and `sub_82EDF460` (the XDK vector memcpy). Nothing
in the closure allocates, frees, signals, submits, locks or calls indirect -- gate 1 is pass, and
so is gate 3 (no timebase) and gate 4 (r3 = 256 is read by the caller).

**Why gate 2.** `sub_82B3DF90` zero-fills through the pointers at `out+4` and `out+8`, and those
pointers are the segment output addresses `sub_82B3DC48` computes *during* this call, from
`sub_82B3DB90`'s return values; its fill lengths then depend on the same values. Nothing about
either fill region exists before the call, so no window can name it. Predicting it would mean
re-deriving `sub_82B3DC48`'s loop and `sub_82B3DB90`'s clamps inside this builder -- three
functions deep, where one arithmetic slip writes outside the declared windows and reaches the
live game. The brief's rule applies exactly: "return false when the addresses or lengths only
exist DURING the call". `Windows()` returns false unconditionally and the original runs.

What that costs, and what it does not: the function is still covered piecewise, because every
byte it is responsible for is written by a callee that has its own hook --  `sub_82B3DC48`'s
segment and copy writes, `sub_82B3DF90`'s two fills, `sub_82B3DB90`'s runs. What stays
uncompared is this function's own three words in the caller's record and the window/segment
arithmetic that feeds the callees. If that is wanted later, the cheapest route is not a
prediction chain: promote `sub_82B3DC48` and `sub_82B3DF90` to native, then the only thing this
body adds over them is arithmetic, and a divergence in it shows up as a divergence in theirs.

Widths that matter: `add r7,r6,r30` (position + consumed), both `mullw`s, `add r11,r8,r11` and
`add r10,r7,r11` (the ring bounds), `add r3,r8,r11` (the cursor) and `subf r10,r27,r10` are
64-bit on zero-extended words -- a carry into bit 32 is in the register and invisible in the
stores, so the body keeps 64-bit intermediates and casts at the stores. The two `tw` guards
(`twllei r3,0` on the span, `twlgei r4,-1` on the divide) are reproduced at the same points;
`ppc_trap(type 0)` only warns and returns.

Unsure: `+16` is read as a word count (`sub_82B3DF90.inc` names it `kBlock` for the same use);
`+20`/`+24` as counts because their difference is scaled by four before being added to a byte
address. Window `+8` is written here and read by nothing in the five functions -- either dead or
consumed somewhere outside the family.
