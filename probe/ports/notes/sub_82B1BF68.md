# sub_82B1BF68

Leaf, 13 lines, no callees, no imports, no indirect calls, no timebase, no locks.
Argument: r3 = pointer to an object with a u32 at +16. Behaviour: read `u32 [r3+16]`, return it in
r3, then store 0 over it -- a detach/take accessor. Load and store address the same word, so the
order (load, then clear) is load-bearing and the port keeps it; `object` is captured from r3
before r3 is overwritten by the loaded value.

Width: `lwz` zero-extends into the 64-bit register, so r3 is `0x00000000_xxxxxxxx`; the port
assigns `ctx.r3.u64 = REX_LOAD_U32(...)`, matching the lifted line exactly.

Stores: one, `stw` to `r3 + 16`, 4 bytes, base register provenance `entry` (r11 = r3, never
reassigned). Window: `{r3 + 16, 4}` -- known from entry state alone, 4 bytes of a 32 KB budget.
Read set: the same word, declared separately so a dumped vector replays without reaching for the
window snapshot.

Structure unnamed: nothing in docs/rw_audio_structs.h has this shape (rw_xma_stream has a u32 at
+0x10, sample_credit, but that object is driven by sub_82B50B80 and is not reached through method
slots, so the match is coincidental and no name is asserted). Adjacent sub_82B1BF80 is the same
detach over +0 and sub_82B1BF60 is an empty `blr`, which reads as a set of small method slots over
one object.

Callers: no `sub_82B1BF68(ctx` call exists in the lifted tree -- the address appears only in
skate3_init.h / skate3_init.cpp / skate3_register.cpp -- so all 64,662 boot calls arrive through
function-pointer dispatch. A caller can therefore only consume the ABI return register, hence
`kReturnR3`; that value is computed identically to the original, so naming it cannot produce a
false divergence even if some call sites ignore it. Scratch r10/r11 are left untouched by the
rewrite (volatile, not compared), as in the verified siblings.

Gates: 1 pass (leaf, nothing allocates/locks/signals), 2 pass (single entry-relative store),
3 pass (no `mftb`), 4 pass (r3 named).
STATUS: pending. Unsure of nothing material; the only unverified item is the semantic guess
("detach/take"), which does not affect the rewrite.
