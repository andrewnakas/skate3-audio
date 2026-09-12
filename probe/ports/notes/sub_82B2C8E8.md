# sub_82B2C8E8

Leaf, 7 lines, two instructions: `mr r3,r6` then `blr`. It returns its fourth argument
unchanged and does nothing else -- no loads, no stores, no callees, no branches, no CR or XER
write, no timebase.

Arguments: r3, r4, r5 are untouched; r6 is the value returned. The move is 64-bit
(`ctx.r3.u64 = ctx.r6.u64`), so the upper half of r6 is carried into r3 verbatim; a 32-bit
copy would be a divergence whenever a caller leaves junk above bit 31.

Stores: none. Window: empty, `Windows()` returns true (nothing to snapshot or rewind, and no
read set to record -- the entry registers in the vector are the whole input).

Result mask: `kReturnR3`. Not gate 4: r3 is the ABI return register and the only thing either
body writes, so comparing it compares everything the function produces. If some caller ignores
r3 the comparison is merely vacuous, never a false divergence.

Gates: 1 pass (leaf), 2 pass (empty write set), 3 pass (no timebase), 4 pass (r3 named).

Unsure / for the next person: what it is *for*. 0x82B2C8E8 is never the target of a `bl`
anywhere in the lifted corpus, so it is only ever reached through a pointer slot -- 129,324
calls per boot on `RwAudioCore Dac`, with the same first-call entry registers in all six traced
sessions (r3=40C215D0, r4=49603D80, r5=00000001; the tracer does not record r6, so the returned
value is unobserved). Its neighbours look like slots of one small class -- 82B2C8C0 is
`li r3,44` (a size), 82B2C8C8 writes the pointer 0x8231B924 to +0 of its argument, 82B2C8F0 is a
two-object update returning 1 -- but nothing here verifies that this function sits in that table,
so the role line says only what the instructions say.
