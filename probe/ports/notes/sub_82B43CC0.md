# sub_82B43CC0

Builds the five normalised coefficients of a low-pass biquad from one angle. Args: r3 = the
20-byte coefficient block, f1 = w, the cutoff in radians per sample. Returns nothing; r3 is never
written, f1 is left holding the last quotient and both call sites ignore it.

Callees, both through GuestCall: **sub_82F4DED0** (sine) and **sub_82F4DFB0** (cosine). Each
writes only its own frame below r1 -- no guest state, no indirect call, no timebase, no lock --
so neither needs a window. Census: gate1 pass, depth 0, closure size 2.

The four constant-pool loads were computed as ((lis_imm & 0xFFFF) << 16) + offset and then **read
out of the dumped image** (probe/harness/out/image) rather than guessed:

    0x8209975C = 0.5   0x8231A844 = 1.0   0x82094178 = -2.0   0x82060C50 = 2.0

which identifies the whole function as the RBJ low-pass at Q = 1: alpha = sin(w)/2,
a0 = 1 + alpha, a1 = -2 cos w, a2 = 1 - alpha, b0 = b2 = (1 - cos w)/2, b1 = 1 - cos w, every
coefficient divided through by a0. That also names the block sub_82B43AF8 consumes:
[a1/a0, a2/a0, b0/a0, b1/a0, b2/a0].

Stores (4 bytes each, f32): r3+0, r3+4, r3+8, r3+12, r3+16. Nothing else outside the frame.

Two things kept deliberately:

- r3+8 and r3+16 are the SAME expression, `fdivs f9,f4`, executed twice. The results agree, but
  the second divide is reproduced as a divide -- not as a copy of the first store and not as a
  multiply by 0.5, neither of which is the instruction that ran.
- `fdivs f5,f0,f7` gives 1/a0, and a1/a0, a2/a0 and b1/a0 are **multiplies by that reciprocal**
  while b0/a0 and b2/a0 are **true divides by 2*a0**. So b1 != 2*b0 bit for bit in general. No
  algebraic tidying.

`stwu r1,-112(r1)` IS reproduced, which most ports skip. Both callees spill f30/f31 and scratch
below r1; without the move their stores land on this function's own red-zone spill slots, so the
native run's out-of-window footprint would stop matching the original's. The back-chain word is
written with the same value the original writes, so those bytes are identical after either run.
r1 is restored with `s64 + 112` exactly as the lifted body does.

r31, f30 and f31 are saved and restored in host locals. Both callees are ABI-correct so this is
belt and braces, but it is exactly right: the original restores them from its own spills, so its
exit values are its entry values, and the harness compares r13-r31 and f14-f31.

Window rationale: one span, 20 bytes at r3, known at entry. Returns false only for r3 == 0,
where the original stores through null.

Gate verdict: none fire. Callees replayable (gate 1 pass), write set is a single entry-state span
(gate 2), no timebase (gate 3), the output is entirely in the window so kReturnNone compares
everything a caller can see (gate 4) -- confirmed at both call sites, skate3_recomp.67.cpp:24827
(sub_82B27E20) and :38162, which read only the stored words.

Unsure: nothing about the arithmetic. The one soft spot is the reproduced frame move -- if a
future reader decides ports must never touch r1, this is the function to re-measure first.
