# skate-audio-core

The Skate 3 audio graph in Rust, translated from native C++ that was **first proved equal to
the original recompiled code**. Every function here is a transcription of a body the shadow
harness compared against the running game, so a divergence points at the translation rather
than at a misunderstanding of the engine.

## What is here

| module | what it covers | verification |
|---|---|---|
| `system.rs` | the command ring producer, all four paths | 6,706 recorded comparisons replayed |
| `player.rs` | the three `PacketPlayer` consumers, the FIFO, the liveness scan | 1,679 replayed |
| `buffers.rs` | buffer-pair init | 222 replayed |
| `fp.rs` | the guest's scalar FP idioms: `lfs`/`stfs`, `fcfid`/`frsp`, the single-rounded forms, `fctiwz`, `rlwinm` | unit-tested only |
| `counter.rs` | `sub_82B1F360`, the six-word cascading counter the evaluator draws from | verified C++ reference; unit-tested only |
| `eval/` | the expression evaluator's 40-slot opcode table at guest `0x82FD3600` — **31 slots**, every one that has a verified C++ body | verified C++ reference; unit-tested only |
| `scheduler.rs` | `sub_82B489D0` and `sub_82B39690`: an instance detaching itself from the scheduler, and the bucket list mechanic that removal runs on | verified C++ reference; unit-tested only |
| `cursors.rs` | `sub_82B32550`, `sub_82B349A8`, `sub_82B3C9D8`: the three verified cursor advances — which ring slot, which entry, which segment comes next | verified C++ reference; unit-tested only |

`cargo test` runs 104 unit tests. **Read the next two sections before reading that as one number:
the three original modules and everything added after them are checked in different ways, and only
the first three have replay figures.**

### The two kinds of green in this crate

**Replayed against recorded vectors** — `system.rs`, `player.rs`, `buffers.rs`. Tier 1 is met:
8,607 of 8,607 comparisons from one complete game session replay with 0 disagreements.

```
cargo run --example replay_vectors -- VECTORS.tsv 00000000 3F800000
```

The vectors are recorded by the harness itself (`skate3_audio_vectors_path`) — real inputs the
game generated, not synthetic ones. An address the port reaches that was not recorded makes the
vector **unreplayable**, never zero-filled, because feeding it fabricated input would turn a
failure into a meaningless pass.

**Unit-tested against a verified reference** — `fp.rs`, `counter.rs`, `eval/`, `scheduler.rs`,
`cursors.rs`. The C++ body each of these was translated from was compared call-for-call against
the original under the harness, on real inputs, at zero divergence. The Rust has no vectors of its
own, for one of two reasons. For `fp.rs`, `counter.rs` and `eval/` there is no direct call site in
the lifted tree at all (the evaluator reaches all 40 slots through one `bctrl` on a data word), so
the harness never bracketed them individually. For `scheduler.rs` and `cursors.rs` the harness does
bracket the functions — that is how they were verified — but it records no per-call inputs for
them, so there is still nothing to replay. Either way what this buys is a much smaller search
space — a fault here is a transcription error, not a misreading of the engine — and what it does
not buy is a number.

The unit tests are held to the standard the vector work is: each was checked by breaking the
function it covers and confirming the test fails. **53 negative controls** have been run:

- 28 across `fp.rs`, `counter.rs` and `eval/`; 25 now fail correctly, 21 of them on the first
  attempt;
- 25 across `scheduler.rs` and `cursors.rs` — one per test — all 25 failing correctly on the
  first attempt, with each break restored and re-checked.

Four passed at first and were fixed by writing sharper tests, not by lowering the claim.
`op_round_product`'s multiply order needed inputs where an intermediate product actually rounds —
over small primes a reversed quad gives the identical answer. `op_curve`'s upper-neighbour clamp
needed a non-zero interpolation fraction. `op_curve`'s nearest-mode test needed a scale *above*
1.0 as well as below. `op_envelope`'s mode-word reload needed the aliasing case where the mode
word *is* one of the words the call stores.

Three still pass, and each is an equivalent transformation rather than a weak test:

- the unrolled trip count in `op_round_product` and the two summers — reducing it leaves the
  remainder to the trailing loop, which visits the same words in the same order and reads the same
  addresses. The only residual difference is which operand of a commutative multiply comes first,
  and `docs/vmx128-exactness.md` rule 4 records that float ops are not NaN-commutative while the
  winning operand is chosen by register allocation and cannot be derived from source at all;
- deriving a completed segment's next slope from the value word rather than from the target just
  reached, in `op_envelope` — the word was stored from that target and the round trip is
  single-exact;
- moving `op_envelope`'s sign test after its byte store — both operands are already in locals.

Those three are reproduced as the original has them anyway, and said so in their doc comments, but
no test in this crate would catch their absence.

`scheduler.rs` and `cursors.rs` add **six more of the same kind**, each measured the same way — by
making the change and watching all 104 tests still pass — rather than assumed:

- `recycle_node` re-reads the node's two link words between the neighbour stores instead of
  hoisting both loads, which differs only when a neighbour's link field overlaps the node's own;
- `detach_instance` loads `instance + 0` after storing the parked bucket index, which differs only
  if that store lands on the node pointer — the input the C++ `Windows()` refuses as gate 2;
- `advance_ring_cursor` reloads the cursor byte it has just written, and stores zero into `+432` a
  second time on the latch path. The second of those is the same value to the same address, so it
  is invisible to a single-threaded compare in either direction, like the ring's publish ordering;
- `advance_segment_position` reloads `+49` after retiring a segment, and `+49` and `+36` again
  before addressing the next one — all three differ only for a segment table that overlaps the
  object's header.

One reload of this family *is* pinned, by `scheduler.rs`'s
`the_free_head_is_re_read_after_the_nodes_link_words_are_written`. Read that test's comment before
quoting it: the aliasing layout it uses is one the C++ `Windows()` refuses to bracket, so what it
establishes is that the reload survived the transcription, **not** that the guest agrees with the
answer. Nothing establishes the latter.

### Limits carried over from the harness

From `docs/shadow-harness.md`:

- A large share of `EVENT_SUBMIT` passes verify one write **vacuously**: on an empty FIFO that
  word is already 0 on entry and 0 in the expectation.
- All recorded liveness queries arrived with an empty FIFO, so the list-walk branch is
  **unreachable by these sessions**, recorded as a permanent limit rather than a pending task.
- `EVENT_PLAY` is verified at one input point: 48 kHz, six channels.

Four divergences from the original are deliberate and pinned by tests. The guest's `fctidz` and
Rust's saturating `as i64` disagree at exactly 2^63, so that conversion is written branch for
branch; `fctiwz` and `as i32` disagree on NaN, likewise; the ring's publish ordering is
inverted, which leaves memory byte-identical and is therefore invisible to a single-threaded
compare in either direction; and `scheduler::detach_instance` returns an out-of-segment `Error`
where a null node would have sent the original to guest address 8 — the same choice
`eval::state::op_shuffle_bag` makes, and for the same reason: the C++ `Windows()` refuses that
input, so nothing is known about what the guest does there and inventing a write would turn a gap
in coverage into a wrong answer.

One behaviour is reproduced rather than fixed and can hang the caller: `eval::wave::op_oscillator`'s
phase-wrap loop does not terminate on a NaN or infinite phase, because the guest's unordered compare
does not terminate either. Its doc comment says so.

## The evaluator

`eval/` is the crate's second real subsystem. The interpreter `sub_82B1E290` walks a list of nodes,
and for each record in a node's program it calls `TABLE[opcode]` with an operand block in `r3` and
stores the returned low word back into the block. The table lives at guest `0x82FD3600` and was read
out of the validated image dump: exactly 40 entries, of which

- **31 are ported**, every slot with a verified C++ body;
- **3 fail the port screen's gate 1** — each makes an indirect call, so neither language has a
  verified reference for them;
- **1 is a pending path split** (`sub_82B1C210`, given a C++ body on 2026-09-12, comparable only on
  the inputs that skip its listener broadcast). Nothing unverified is translated here, so it waits;
- **5 are outside the 216 audio-thread functions** and have never been screened at all.

`eval::TABLE` carries all 40 rows with the reason for each gap, and `eval::dispatch` routes an
opcode the way the `bctrl` would. An unported opcode is an `Error` naming the function, never a
zero: the interpreter would store *something*, and inventing a value would turn a gap in coverage
into a wrong answer.

The interpreter itself is **not** here. It fails gate 1 and gate 2, so it has no verified C++ body
to translate; a Rust version would be new analysis rather than transcription.

| submodule | slots | what they are |
|---|---|---|
| `eval/arith.rs` | 13 | add, subtract, multiply, divide, remainder, min, max, saturating subtract, capped multiply, two summers, two rounding multipliers |
| `eval/accessors.rs` | 7 | three take-and-clear accessors, a stack top and push, an any-nonzero reducer, a flag-table select |
| `eval/state.rs` | 8 | hysteresis window, stepping cursor, timer, ramp, delay ring, shuffle bag, and two draws from `counter.rs` |
| `eval/wave.rs` | 3 | oscillator (quarter-sine table, pulse, ramp, triangle), multi-segment envelope, sampled curve |

## Design

Guest structures are **byte-addressed big-endian accessors over `&mut [u8]`**, not idiomatic
Rust structs. These are recovered layouts with asserted offsets, and the per-function criterion
compares bytes against the verified C++ — a byte-addressed view makes that direct instead of
routing it through a serialisation step that could hide a discrepancy of its own. Offsets are
asserted at compile time, mirroring `docs/rw_audio_structs_check.c`.

Guest constants are read **live** through the `Guest` map rather than folded in, because that is
what the originals do, because two of them are not constants (the scheduler's tick scale is written
at run time), and because a patched image should reach the ports. `eval`'s module documentation
records each cell's dump value alongside a compile-time assertion of the `lis`/`addi` arithmetic
that forms its address — one misread constant in `sub_82B2FE00` caused this project's first shadow
divergence.

Every evaluator slot has the same signature, `fn(&mut Guest, u32) -> Result<u64>`, including the
ones that write nothing. That is the guest's own signature for all 40 slots and it is what makes
the table dispatchable; each op's doc comment states its write set, which the signature does not.
The `u64` return is the guest's full `r3`: the interpreter keeps only the low word, but several ops
legitimately leave bits above 31 set, and the harness compares all 64.

Two callees in `player.rs` are **closure parameters**, not ports: the decoder teardown and the
restart branch, both of which make indirect calls. Neither is portable, and the first is exactly
why `EVENT_STOP` has no comparable path under the harness.

## Not written yet

`xma.rs` (the paired ring protocol against a decoder trait), `dsp/` (one file per plug-in family)
and `graph.rs` (instantiation from descriptor metadata). Inside `eval`, the interpreter's node walk
and the nine unported slots, for the reasons above.

**The scheduler tick cannot be written, and that is not a backlog item.** `docs/PLAN.md` section 6
asks `scheduler.rs` for the "two-bucket tick, per-plug-in profiling toggle, mid-tick self-removal";
only the last of the three is in `scheduler.rs`. The tick is `sub_82B48A50`, recorded `gate-1` in
`docs/ports.md`: it calls each node's process function through a `bctrl`, and it reads the timebase
through `sub_82B1F7E8` twice per node, which is gate 3 as well. Neither language has a verified
reference for it, and the profiling toggle is a field that tick writes. A Rust version would be new
analysis dressed as a transcription. Its two neighbours in the PLAN's Phase 2 list are out for the
same reason — `sub_82B48440` is gate-1 through the allocator and `sub_82B482F8` is gate-2.

Two verified functions in the same area were **considered and left out** on the status column
rather than the gate: `sub_82B376B8` (the metering tick) and its callees `sub_82B370E8` and
`sub_82B373C8` are recorded `thin` in `docs/ports.md` — verified, but on too few calls for their
size to carry promotion — and `sub_82B373C8` is a VMX128 kernel besides, which this crate has no
vector layer for until PLAN Phase 3 lands. Translating a `thin` body would blur a distinction this
README exists to keep.

All 216 audio-thread functions have a verified or gate-labelled C++ reference in
`recomp/src/audio_ports/`, so the remaining modules are transcription work rather than analysis.
See `docs/PLAN.md` Phase 4 and section 6.
