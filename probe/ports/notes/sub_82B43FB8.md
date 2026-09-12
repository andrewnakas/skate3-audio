# sub_82B43FB8

Leaf, 610 lines, no callees, no timebase, no vector ops. A linearly interpolating resampler:
r3 = output sample count, r4 = float table (already biased by the caller), r5 = output buffer,
r6 = a u32 whole-sample cursor, r7 = a word whose **high half** holds the 16-bit phase fraction,
r8 = the 16.16 phase increment. No structure offsets at all, so `docs/rw_audio_structs.h` has
nothing to name. All three call sites (`skate3_recomp.67.cpp:38537/39253/46775`) pass r6 and r7 as
stack scratch slots that they pre-load with the cursor and with `fraction << 16`, and read the
cursor back afterwards; none reads r3, hence `kReturnNone`.

Per output sample j: `phase = fraction + j*step`, `out[j] = fmadds(fsubs(t[i+1], t[i]),`
`fmuls(frsp(fcfid(phase & 0xFFFF)), 1.5258e-5), t[i])` with `i` the cursor plus the accumulated
`(phase >> 16) & 0xFFFF`. The weight cell `0x822F87AC` is `0x377FFC9C` = the literal `1.5258e-5`,
**not** 1/65536 (`0x37800000`) — read from the image dump, loaded live by the body.

Three loops tile the buffer: eight samples/32 bytes per trip up to `r5 + ((count<<2) & 0x3FFE0)`,
then four samples/16 bytes while `ceil(remaining/4) >= 4`, then one at a time via `stfsu`. The
first loop precomputes eight phase offsets from `2*step` truncated to 32 bits plus k*step in 64
bits (so they are `(2*step mod 2^32) + k*step`, kept literal); the other two chain the phase one
step at a time. Load/store interleaving is preserved trip by trip — in the eight-wide loop twelve
loads, `stfs 4/8/0(r5)`, four `+4` loads, then `stfs 12/24/16/20/28(r5)`; in the four-wide loop
sample 2 loads `+4` before `+0` — because the output buffer may alias the table.

Stores: `{r5 + 4k, 4}` for every sample, then `{r6,4}` and `{r7,4}`, in that order, on every path
(count 0 still republishes both). The `stw` at r7 is four bytes over what the callers wrote as a
word, so it also zeroes r7+2..3. Windows: `{r5, (count<<2) & 0xFFFFFFFC}` + `{r6,4}` + `{r7,4}`,
returning false when that exceeds the 32 KB budget or would wrap 2^32. The `std`/`lfd` fraction
spills at -184..-240(r1) are the function's own frame (there is no `stwu`; r1 is the caller's) and
are not windowed. Only the low 32 bits of r5/r14 are ever consumed, so the cursors are u32 here.

Reads: the weight cell, and the table span `[t + 4*cursor, t + 4*(last+2))` where `last` is the
closed form `cursor + N*(step>>16) + ((fraction + N*(step & 0xFFFF)) >> 16)`. That form is the
true bound only while eight steps cannot overflow the 16-bit whole-part field, which every loop
masks; when it can, or when the span is wider than the budget, the table read is **left
unrecorded** rather than guessed — reads are replay metadata and are never compared, so a
recorded vector may lack its table bytes on those calls. r6/r7 are deliberately not in the read
set: input spans are dumped after the lifted body runs, so for a span the function also writes
that would record the result; their entry bytes are already in the write windows.

Gates: 1 pass (leaf), 2 pass (write set is r3/r5/r6/r7 only), 3 pass, 4 pass (stores).
STATUS pending. Unsure: nothing about the write set; only whether a real call ever passes a
fraction with bits above 16 set (the `clrldi` paths would then weight sample 0 with a >1 value —
reproduced literally either way), and whether the r7+2..3 bytes the 32-bit store zeroes belong to
a neighbouring field the callers care about.
