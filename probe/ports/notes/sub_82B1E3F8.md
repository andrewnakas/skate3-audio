# sub_82B1E3F8

- Role: `this* f(this*, uint32 flags)` — a destructor in the Xbox 360 EA/RenderWare shape.
  It installs the vtable pointer `0x822FBD5C` at `*this`, and when bit 0 of `flags` is set it
  calls `sub_828AAF88` for the allocator and dispatches the allocator's vtable slot `+12`
  (`free`) with `(allocator, this, 0)`. It returns `this` either way. 57 lifted lines, one
  direct callee, one own indirect call, no imports, no timebase, no lock. 514 boot calls on
  `RwAudioCore Dac` (tier D).
- Arguments: r3 = `this`, r4 = flags (only bit 0 is read, via `clrlwi r10,r4,31`).
- Constant: `kVtable = ((-32208 & 0xFFFF) << 16) + (-17060) = 0x82300000 - 0x42A4 =
  **0x822FBD5C**`. Computed, not read off by eye; the lifted `lis` leaves `s64 = -2110783488`,
  the sign extension of `0x82300000`, which confirms the immediate.
- Stores: one outside this call's own frame — `stw r9,0(r3)`, 4 bytes, `u32[this+0] = 0x822FBD5C`.
  The other three (`-8(r1)` link, `-16(r1)` r31 save, the `stwu` back chain) are the frame and are
  never windowed; the frame is still reproduced because both callees run on it.
- Result: r3 = `this` (`mr r3,r31`). Mask `kReturnR3`.
- Gate 1 **fails**, twice over, at depth 0 — this function's own `bctrl` at **0x82B1E43C**:
  1. the target is `u32[u32[allocator+0]+12]`, called with r5 = 0 — a heap free, which cannot be
     replayed against rewound memory;
  2. `sub_828AAF88` (skate3_recomp.45.cpp:7080) itself lazily initialises the heap through
     `sub_828AB0E8` on first call, and its transitive closure is 131 functions, all outside the
     audio corpus.
  Neither is on a path predictable-and-excludable from entry state: bit 0 of r4 predicts the
  path, but the destroying path is the interesting one and it is the one that frees.
- The write set I WOULD have declared if it were comparable: `spec.write(r3 + 0, 4)` and
  `spec.read(r3 + 0, 4)`, plus the allocator's own set — which is precisely what makes it
  unenumerable as well as unreplayable. Windows() returns false and is unreachable.
- Unsure: whether `sub_828AAF88` returns a per-thread or a per-heap-id allocator. It indexes a
  108-byte stride table by a global word (`lwz r11,-10752(r10)` off `lis r10,-31988`) and returns
  that record `+12`, so the answer is "whichever the global selects" — it does not change the
  rewrite, only what a Rust port would have to model.
- Sibling functions, identical instruction for instruction apart from the vtable constant:
  `sub_82B23C78` (`0x8231B924`) and `sub_82B3C810` (`0x8231BAA0`).
