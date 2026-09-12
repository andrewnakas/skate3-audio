# sub_828E2EA0 -- unlink a node from the container's `+8` list, free the container at zero

`r3` = the container, `r4` = the node; `next` at `+0`, `prev` at `+4`. Returns the literal 0,
and `sub_82B1BF98` ignores it (`skate3_recomp.66.cpp:65913`).

**This is `sub_828E2E08` with exactly one offset changed**: the cursor it repairs lives at
`container+8` instead of `+12`. Instruction for instruction the two are otherwise identical --
same link offsets, same count at `+4`, same allocator global, same free slot, same `li r3,0`,
89 lifted lines each, 154 calls a boot each. Read `probe/ports/notes/sub_828E2E08.md` for the
full walk-through; only what is specific to this one is repeated here.

Steps: advance the `+8` cursor to `u32[node+0]` if it names this node; `u32[prev+0] =
u32[node+0]`; `u32[next+4] = u32[node+4]` (both links re-read from the node, not cached across
the first store); `addic.` the count at `+4` and store it back; when the low word reaches zero
and `u32[0x83083CCC]` is non-null, `free(allocator, container, 0)` through vtable slot **+12**.
The node's own links are left stale.

`0x83083CCC` computed as `((-31992 & 0xFFFF) << 16) + 15564` = `0x83080000 + 0x3CCC`.

The decrement is 64-bit on a zero-extended `lwz`, so a count already at 0 stores `0xFFFFFFFF`
and does **not** trigger the free. Reproduced, not fixed.

## Why there are two of these

`sub_82B1BF98` calls `sub_828E2E08` and then `sub_828E2EA0` on the same container
(`u32[owner+8]`) with two nodes embedded 20 bytes apart in the same element
(`u32[owner+4] + 24`, then `+20`). So an element is registered in two lists of one container,
each list carrying its own cursor (`+12` and `+8`), and the shared count at `+4` counts
registrations across both. Two functions exist because each list's cursor field is baked into
the code -- template instantiation or hand-duplication, indistinguishable from here.

## Unverifiable, and why

**Gate 1**, at depth 0: the `bctrl` at `0x828E2F20` is an allocator *free* through a vtable
slot loaded from `u32[0x83083CCC]`. Replaying the native body on rewound memory would free the
container twice.

As with `sub_828E2E08` the gate is path-dependent and predictable from entry state
(`REX_LOAD_U32(container+4) == 1 && REX_LOAD_U32(0x83083CCC) != 0` is the only path that
frees), so a future harness could compare the unlink on every non-final call. Not built here.

## The write set it would have declared

    const uint32_t c = ctx.r3.u32, n = ctx.r4.u32;
    if (REX_LOAD_U32(c + 4) == 1 && REX_LOAD_U32(0x83083CCC) != 0) return false;  // the free
    spec.write(c + 8, 4);                        // the cursor, only when it names this node
    spec.write(c + 4, 4);                        // the count
    const uint32_t prev = REX_LOAD_U32(n + 4);
    if (prev != 0) spec.write(prev + 0, 4);
    const uint32_t next = REX_LOAD_U32(n + 0);
    if (next != 0) spec.write(next + 4, 4);
    spec.read(c + 4, 8);  spec.read(n + 0, 8);  spec.read(0x83083CCC, 4);

Result mask `kReturnR3`, the constant 0.

## Unsure

Same three as `sub_828E2E08`: whether `+4` is a registration count or a refcount, what the
container type is (nothing in `docs/rw_audio_structs.h` matches), and whether the allocator at
`0x83083CCC` is the one `sub_828AAF88` returns.

## Split and armed, 2026-09-12

Converted from gate-1 to the path split this note proposed, identically to `sub_828E2E08` — see that
note's "Split and armed" section for the full reasoning, including why each store address is checked
against the words read after it. STATUS is `pending (partial: ...)`.

- **Predicate:** false when `REX_LOAD_U32(container+4) == 1 && REX_LOAD_U32(0x83083CCC) != 0`, true
  otherwise, plus the same aliasing declines. The only difference from `sub_828E2E08` is that the
  cursor span is `container+8`.
- **Comparable write set:** at most four 4-byte spans — the cursor at `+8` (only when it names this
  node), `prev+0`, `next+4`, the count at `+4`. Reads `{container+4, 8}`, `{node+0, 8}`, the
  allocator cell.
- **Expected fraction:** the overwhelming majority of the 154 boot calls, for the same reason.
- **Stays unchecked:** the free.
- `Overlaps()` is duplicated in this file rather than referenced from `port_828E2E08`. Both are in
  the same aggregator and the lint would allow the reference, but four lines copied are cheaper to
  audit than a cross-port dependency.
