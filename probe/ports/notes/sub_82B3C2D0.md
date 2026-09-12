# sub_82B3C2D0 -- time the Dac update, smooth the frame time, retire voices on a budget

Takes no arguments. Works entirely on the profiler block at `0x830BDEBC`
(`lis r11,-31988 ; addi r31,r11,-8516`) and on the Dac object its `+0` field points at.
Called 18,684 times in a boot session, from `sub_82B218E8` and from `sub_82B219E8`;
both callers ignore `r3`.

Four `mftb` reads, in order: one at entry (kept in r28 for the final elapsed figure), one
folded into the frame-time history, one stamped into `+8`, and two in the tail that fold the
pass into `+4` and record the whole call's duration into the Dac's `+240`.

Profiler block fields, inferred from use here and in `sub_82B219E8` / `sub_82B217F0`, which
touch the same cells. Nothing in `docs/rw_audio_structs.h` names them:

| off | size | use |
|---|---|---|
| +0  | 4 | the Dac object this thread services (also what `sub_82B3C440` reads) |
| +4  | 4 | accumulated work ticks, zeroed every pass and refilled in the tail |
| +8  | 4 | the last timebase stamp |
| +16 | 4 | f32 the smoothed frame time: (slot0 + slot1 + this pass) * pool+440 |
| +20 | 4 | f32 history slot 0, and the `stfsx` array base |
| +24 | 4 | f32 history slot 1 |
| +28 | 4 | which slot to write next, toggled by `cntlzw` -- 1 if the old value was 0, else 0 |

Body: read the accumulator and the last stamp, subtract them in 64 bits (a borrow leaves the
upper half set; only the store truncates), add the second timebase read, mask to 32 bits,
`fcfid`/`frsp` it into a single, add the two history slots, scale by pool+440 and store the
result at +16; write this pass's figure into the history slot the old +28 selected; zero +4;
toggle +28. Then, if the Dac's load at +224 is below `0x820ED57C`, sum `cost_scale *
(smoothed + every voice's +0)` over the `+280` voices hanging off `+108`, subtract
`load * pool+2148`, and while that surplus is positive call `sub_82B3C440` for the next
retirable voice, deduct its cost with one `fnmsubs`, and pass it to `sub_82B49100(voice, 2)`.

## One detail that must not be tidied

The per-voice cost scale is loaded into `f12` **before** the retirement loop and read again by
the `fnmsubs` **after** `bl 0x82b3c440`, without a reload, on the loop's first iteration only
(`b 0x82b3c3e4` jumps past `loc_82B3C3E0`, which is where every later iteration reloads it).
`f12` is volatile on this ABI, so what the `fnmsubs` multiplies by is whatever the callee left
there. The port therefore holds that value in `ctx.f12.f64` rather than a C++ local: a local
would preserve the pre-call value and silently diverge from the original the day a callee
touches `f12`. Neither `sub_82B3C440` nor `sub_82B49100` nor `sub_82B49438` writes `f12` at
its own level -- checked -- but `sub_82B49100`'s deeper closure was not proven clean, and
keeping the value in the register file makes the proof unnecessary.

Constant cells, each computed as `((imm & 0xFFFF) << 16) + offset`:
`0x822F87B8` (frame scale), `0x822F8E64` (load-to-target scale), `0x820ED57C` (the load
threshold), `0x820ED958` (per-voice cost scale), `0x82165A10` (0.0f, the cell
`docs/command-queue.md` names).

## Unverifiable, and why

Gate 3. Every path reaches `mftb` through `sub_82B1F7E8`, four times over. Two runs of the
same call return two different tick counts, so the original's result and the rewrite's differ
by construction: the stores at +4, +8 and Dac+240 all carry raw tick values, and the float at
+16 carries a tick delta. No care in the port changes that, and `Windows()` returning false
is moot because the macro never arms the shadow branch for a gate-labelled port. The body was
written anyway: it is the readable form, and it is the reference for the Rust port.

Two further gates would fail even with a stubbed timebase, so a future harness needs more
than a fake clock:

- **Gate 1.** `sub_82B49100` unlinks the voice from a list and rewrites it (`+0/+4/+8` floats,
  `+28/+32/+36/+60/+71/+76`, plus the neighbours' link words) and calls `sub_82B49438`. Its
  closure leaves the audio corpus (`82F4DC60`, `82F52B30`). `sub_82B3C440` is safe -- it
  writes nothing outside its own frame -- but the retirement is not replayable.
- **Gate 2.** The retirement loop's write set only exists during the call: which voice
  `sub_82B3C440` returns depends on state `sub_82B49100` has just changed, and the loop's
  length depends on a float budget recomputed each turn.

## The write set it would have declared

From entry state, with `dac = REX_LOAD_U32(0x830BDEBC)`:

    spec.write(0x830BDEBC + 4, 8);    // +4 the accumulator, +8 the stamp
    spec.write(0x830BDEBC + 16, 16);  // +16 smoothed, +20/+24 history, +28 the slot index
    spec.write(dac + 240, 4);         // the pass's elapsed ticks
    spec.read(0x830BDEBC, 32);
    spec.read(dac + 224, 4);
    spec.read(dac + 280, 2);
    spec.read(dac + 108, 4);
    spec.read(0x822F87B8, 4); spec.read(0x822F8E64, 4);
    spec.read(0x820ED57C, 4); spec.read(0x820ED958, 4); spec.read(0x82165A10, 4);

The `+16..+31` span deliberately over-covers: the `stfsx` index is `(REX_LOAD_U32(+28) << 2)
& 0xFFFFFFFC` and is 0 or 4 in practice, but nothing in the code bounds it, so a slot value
above 2 would store past +31 and outside that window. A real Windows() must therefore read
+28 and either window the computed address or return false when the index exceeds 1. Add
every byte `sub_82B49100` touches per retired voice -- not enumerable, per gate 2 above.

## Unsure

- `r3` on return holds the fourth timebase read. Both call sites ignore it, so `kReturnNone`
  would describe the ABI better; the mask says `kReturnR3` because `lint.py` rejects a port
  that declares neither a write nor a result register, and the gate label means nothing is
  compared either way.
- The `stfsx` reload of `+28` after the store is reproduced (the store aliases `+28` when the
  index is 2). Whether the original author intended the alias or the compiler simply could not
  prove it away is unknowable from the lifted form.
