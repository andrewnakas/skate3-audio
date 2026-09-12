# sub_82B1BF98

- Role: **tear down one described element**. `void f(self*)` -- no `li r3`, so r3 is whatever the
  final free left. 247 lifted lines, five direct callees, two own `bctrl`. 154 calls per boot on
  `RwAudioCore Dac`, the same 154 as `sub_828E2E08` and `sub_828E2EA0`.
- Arguments and structures. `self` is three words: `+0` the layout descriptor, `+4` the element
  instance, `+8` the list container. On the descriptor: `+28` u16 instance count, `+32` u16 count
  of the fixed-stride handle run, `+34` u16 count of the variable-stride run, `+36` u8 count of the
  first offset run, `+37`/`+38` u8 flags for the two embedded nodes, `+39` u8 count of the second
  offset run, `+60` a u32 offset table holding **both** runs contiguously. Inside the element:
  `+24` the first embedded node, `+44` (`+24` then `+20`) the second, then the handle records.
- Flow, in order:
  1. `u8[desc+37]` -> `sub_828E2E08([self+8], element+24)`, unlink from the container's **+12**
     list, and advance the cursor 20 bytes.
  2. `u16[desc+32]` iterations of `sub_828E30B8(cursor, cursor+8)`, stride a fixed 28.
  3. `u8[desc+38]` -> `sub_828E2EA0([self+8], cursor)`, unlink from the container's **+8** list;
     then the second run's cursor becomes `cursor + (u8[cursor+16] + 5) * 4`.
  4. `u16[desc+34]` iterations of `sub_828E2D78(cursor, cursor+8)`, stride
     `(u8[cursor+24] + 7) * 4` read **after** the call.
  5. `u8[desc+36]` iterations over `desc+60`: `slot = [entry] + [self+4]`, and when `u32[slot+8]`
     is non-null call its **vtable slot 0** (`bctrl` 0x82B1C0B8) and store 0 over `slot+8`.
  6. `u8[desc+39]` iterations continuing the same table with `lwzu` (so the second run starts at
     the word the first stopped on): same `slot` computation, `sub_828E2C78(u32[slot+8])` when
     non-null, one argument only.
  7. `sth u16[desc+28] - 1` (64-bit `addi`, low halfword stored, so 0 wraps to 0xFFFF), then
     `free(allocator, element, 0)` through vtable slot **+12** of `u32[[0x8307762C] + 36]`
     (`bctrl` 0x82B1C140).
- The two nodes 20 bytes apart are the pairing `sub_828E2E08`'s note describes: one element is in
  two lists of one container (cursors `+12` and `+8`), and their shared count at `container+4` is
  decremented twice here, so the container is freed by whichever of these two calls takes it to
  zero -- inside this function, not at its end.
- Reload discipline, the part most likely to be got wrong. `self+0` is reloaded at seven distinct
  points and `self+4` inside both offset loops. The descriptor pointer live at step 7 is the **last
  of those reloads**, never a fresh read: whichever path ran last (`loc_82B1C100`,
  `loc_82B1C0C0`, or `loc_82B1C038`) left it in r11, and `lbz r11,38(r11)` at `loc_82B1C00C`
  overwrites r11 with a byte, which is why the reload at `loc_82B1C038` exists at all. The port
  models this with one `descriptor` variable reassigned at exactly those points.
- Stores by this function: `stw 0 -> slot+8` inside loop five (r28 is still the zero from
  `loc_82B1BFD0`; it only becomes the loop-six counter afterwards), and `sth -> desc+28` once.
  Everything else is a callee's write, plus the element's own memory going back to the allocator.
- Result mask: **honest mask is none** -- the function returns nothing and every caller ignores it.
  Declared `kReturnR3` because a false `Windows()` with `kReturnNone` trips lint check 5; the value
  there is the free's return, which is not this function's result.
- Gate: **1, fail**, depth 0, indirect 2. The `bctrl` at 0x82B1C140 frees the element itself and
  the one at 0x82B1C0B8 is a release whose implementation is unknown; `sub_828E2E08` and
  `sub_828E2EA0` each reach a container free one level down. A replay on rewound memory would free
  the element twice. `Windows()` returns false. Gate 2 also fails: the write set is the union over
  four counts read live from the descriptor and over the callees' unlinks, whose targets are
  pointers inside lists the calls themselves rewrite.  Gate 3 passes (no `mftb`).
- Unsure:
  - `0x8307762C` is on the same `0x83070000` page as the evaluator globals `sub_82B1E290`
    publishes (`+30168..+30180`, this one is `+30252`). Whether it is the same object is not
    established; it is read here only for its `+36` allocator field.
  - The `+5` and `+7` biases in the two variable strides. Both look like a header word count
    (`(fields + bias) * 4`), but nothing pins what the bias covers.
  - Whether `[slot+8]`'s vtable slot 0 is a destructor or a release. It is the same slot-0 shape
    `sub_82B1D240` calls a release, and the store of 0 right after fits both.
  - `sub_828E2C78` has no port and is outside the audio corpus (census `closure_outside`), so what
    the second offset run holds is only inferred from the identical `slot+8` fetch.
