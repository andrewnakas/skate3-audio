# sub_82B46FB0

53 lifted lines. `r3` = one of the four sub-objects port_82B47658 describes: `{cursor* +0,
accumulated +4, remaining +8, flag +12}`. One step of the variable-length decoder family:

```
cursor  = u32[obj+0]
len     = sub_82B46EA0(u32[cursor+0], sp+80)   # decode, value written to sp+80
u32[cursor+0] = len + u32[cursor+0]            # the pointer is RELOADED after the call
u32[obj+4]    = u32[obj+4] + u32[sp+80]
```

So it consumes one code from the stream and adds its signed value to the sub-object's
accumulator. Both call sites are in sub_82B47010 (`skate3_recomp.68.cpp:33576` and `:33588`), and
both ignore the returned r3; the port still names `kReturnR3` because the value is genuinely
returned, it cannot diverge (it comes from the callee through the same hook in both runs), and a
mismatch there would mean the GuestCall did not happen.

The `stwu` **is** reproduced. The decoded word lands at `sp+80` and that address is passed to
sub_82B46EA0, so skipping the move would put it 112 bytes higher -- in the caller's frame -- and
would also let the callee's own scratch below r1 land on top of it.

The reload of `u32[cursor+0]` after the call is kept even though sub_82B46EA0 provably does not
write it (its only store is the 4 bytes at r4). The brief's rule, and cheap.

Both `add`s are 64-bit in the lifted form on zero-extended operands, and both results are stored
with `stw`. The carry out of bit 31 lives only in r9/r8, which are volatile and uncompared, so the
port keeps `uint64_t` intermediates and casts at the store rather than adding in 32 bits. The
second one matters more than it looks: the decoded value is signed, so a negative code arrives as
`0xFFFF....` and the sum carries on nearly every negative step.

Callee-saved registers: the original spills r30/r31 (and LR) into its own frame because it uses
them across the call. This body keeps both in C++ locals, so r13-r31 are simply never touched and
their entry values survive, which is what the harness compares. The `stw r12,-8(r1)` LR save and
the `std` pair are not reproduced -- own frame, not windowed, LR uncompared.

## Windows

Writes: `{cursor+0, 4}` and `{obj+4, 4}`. Reads: `{obj, 8}` and up to five stream bytes.
sub_82B46EA0's single store is `{r4, 4}` = frame scratch, excluded as this function's own frame.

The census marks this function `gate2_suspect: 1` because the first store's base is a loaded
pointer rather than an entry register. It is enumerable anyway: `u32[obj+0]` is read before
anything in the call writes, and the only two stores are the ones listed -- neither the callee nor
this body can change `obj+0` before it is used, except in the degenerate aliasing case where
`cursor == obj` (then `stw r9,0(r30)` overwrites the cursor pointer itself), and both words are in
the window set regardless, so the rewind covers it.

Refusals: a null sub-object, and a null cursor pointer (the original would store through it).

Gates 1, 3 and 4 clean: sub_82B46EA0 is a verified leaf with no callees, no lock, no allocation,
no indirect call and no timebase.

Uncertain: the stream read is declared as the maximum five bytes rather than the exact width the
prefix implies (port_82B46EA0's own Windows does compute it exactly). Reads are recorded, not
compared, so the only cost is a slightly wide replay vector.
