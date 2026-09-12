# Shadow harness and guest-mix capture: Phase 1, measured

**Phase 1's exit criterion is met, 2026-09-11.**

- **(a)** `EVENT_SUBMIT` ran **1,678 times under the shadow harness with zero register and
  zero memory divergence**, then was promoted and ran natively at least 1,024 times from
  boot to gameplay.
- **(b)** A 4,000-submit `audio_dump_path` capture passes a signal-level layout check, and
  `tools/mixdiff.py` reads it.

Code lives on recomp branch `audio/phase1-harness`, commit `e581969`, with drop-in copies
in `recomp/src/`. Sessions run through `probe/harness/`.

## Running a session

```sh
probe/harness/run_session.sh LABEL [MACRO]     # -> probe/harness/out/LABEL.log, LABEL.guestmix.raw
python3 probe/harness/check_capture.py probe/harness/out/LABEL.guestmix.raw
```

| env | default | effect |
|---|---|---|
| `SHADOW` | `true` | `--skate3_audio_shadow` |
| `NATIVE` | `false` | `--skate3_audio_native`; shadow wins when both are on |
| `PLAY_MOVIES` | `true` | `--skate3_demo_path_play_movies` — see the next section |
| `AUDIO_DUMP_FRAMES` | `4000` | `--audio_dump_max_frames`, 21.3 s |
| `GDB_SCRIPT` | unset | run under gdb; `crash.gdb` stops on SIGFPE and prints the backtrace |

The game ignores SIGTERM. End a session with `pkill -KILL -x skate3`; the capture is
flushed per submit, so it keeps whole records.

## `EVENT_SUBMIT` only runs while a movie plays

In the Phase 0a trace `EVENT_SUBMIT` never ran. The first caller of the PacketPlayer
command producer (`sub_82B28A00`) was the `MoviePlayer2` thread, issuing selector 1, and
the demo path force-completes every frontend movie under boot automation.
`skate3_demo_path_play_movies`, added to the recomp's demo path and off by default, lets
them play. With it on, `EVENT_SUBMIT` runs about 1,700 times across the boot movies and not
again during gameplay.

So **anything on the PacketPlayer path needs a session with movie playback** before it can
be shadow-verified. The producer has no direct call sites in the generated code — it is
reached through a function pointer — so reading the code will not say which other paths
reach it.

## What the harness needed before it could pass a correct function

| | as drafted on macOS | now | why |
|---|---|---|---|
| registers | `memcmp` of the whole `PPCContext` | only what the ABI obliges a callee to preserve — `r1`, `r2`, `r13`–`r31`, `f14`–`f31`, `v14`–`v31`, `v64`–`v127`, `cr2`–`cr4` — plus the return registers the hook names | the lifted `EVENT_SUBMIT` leaves scratch in `r9`–`r11` and `cr6`; a correct native body never reproduces those, so the old compare flagged **every** call |
| memory | one window, ≤ 64 KB | a list of windows, 64 KB in total | `EVENT_SUBMIT` writes four places; the old window covered two of them |
| evidence | a log line on divergence only | milestone counts plus a reporter thread every 10 s | a clean session has to leave positive evidence, and a function that stops being called still needs its final count logged |

The preserved ranges come from the save/restore helpers the image actually uses
(`__savegprlr_14..31`, `__savefpr_14..31`, `__savevmx_14..31` and `__savevmx_64..127`), not
from a generic PowerPC ABI table.

`EVENT_SUBMIT`'s windows are the FIFO head and tail (`player+0x148`, 8 bytes), the new
packet's next pointer (`packet+0x0C`), and — when the list was non-empty on entry — the old
tail's next pointer.

### What the harness cannot verify at all

The native body runs a **second time**, against rewound memory. That is safe for a function
whose effects are memory this harness can rewind — and unsound for one that calls out to
guest code with effects it cannot.

`EVENT_STOP` (`sub_82B28C18`) is the first case: when a decoder is live it calls
`sub_82B3C930`, whose four indirect calls release and unregister the voice. Replaying that
against a rewound copy would tear down an already-released object, and no memory window can
undo a release. So the hook compares only calls that arrive with no decoder, runs the
original for the rest, and counts them (`g_event_stop_unverifiable`). A count that never
drops to a small fraction means the function is mostly unverified, whatever the divergence
figure says.

**Measured, 2026-09-11: `EVENT_STOP` is unverified, not verified.** One session with movies
playing produced **0 comparable calls and 1 skipped**, while `EVENT_SUBMIT` reproduced 1,678
runs at zero divergence in the same session as a control. So the harness was working and the
function simply never arrived on a comparable path — which follows from what it does, since
stopping playback is exactly when a decoder is live. Its native body is written and builds,
and nothing has checked it.

Choosing it first was the mistake this rule exists to prevent, made an hour after writing the
rule down. The same test applies to every later candidate: **before writing a native version,
check what it calls.** A leaf, or one calling only pure-memory helpers like `memset`, is fully
comparable; anything that allocates, frees, releases, signals or submits is comparable only
on the paths that avoid those calls. That is a property of the function, not a shortcoming
to be engineered around — and a promoted native body still has to perform those calls for
real, so the promoted path carries risk the shadow run never covered.

## `EVENT_PLAY` — compared clean, once per boot

`sub_82B28B78` publishes a stream's format onto the player. It clears the decoder pointer,
converts three floats out of the command record into `sample_rate` (+0x154), `channel_count`
(+0x15F) and `format_index` (+0x160), marks `state` (+0x15E) playing, and writes a zero word
plus the format byte through the `source` pointer at +0x50.

It then reloads the state byte it has just set to 1, and calls `sub_82B29018` only if that
byte reads 4 or 0. That callee takes a critical section, makes two indirect calls and calls
three further functions, so the branch is not comparable — but it is reachable only if the two
stores through +0x50 overlap the state byte, which the compiler could not rule out and so had
to emit the reload for. The hook predicts that overlap (and a null source) and counts those
calls rather than comparing them. Predicting it is the point: asserting from source that the
branch cannot fire would be exactly the kind of tidy story this project has been wrong about
before.

**Measured, 2026-09-11, two sessions: 1 comparable call each, zero divergence, zero skipped.**
The skip counter never logged once, which is the positive form of that claim — the aliasing
branch did not fire, so the comparable path is the only one the game took.

One call per session is structural, not a harness limit. `EVENT_PLAY` fires once per stream
start, and a boot plays exactly one frontend movie: with `PLAY_MOVIES=true`, `forcing all
frontend movies complete` appears **zero** times and `FMV rendering NATIVELY` exactly once.
So there is one stream to start, and more boots would repeat the same input rather than widen
it. `EVENT_SUBMIT` reached 1,678 in the same sessions — the third consecutive run at that
exact figure.

What those calls covered, logged once per session so the coverage claim is falsifiable:

| field | record | stored |
|---|---|---|
| `format_index` | `+8`, float `1` | byte `1` |
| `sample_rate` | `+12`, float `48000` | float32 `48000` |
| `channel_count` | `+16`, float `6` | byte `6` |

48 kHz six-channel, the same shape the capture tap records. So `EVENT_PLAY` is verified at one
input point, not over a distribution: other formats, rates and channel counts are unexercised,
as is every `fctidz` edge the conversion reproduces (NaN, values past 2^63, the `>` versus
`>=` boundary at exactly 2^63). **Not promoted.**

## The queue producer — 6,706 calls, and which paths they were

`sub_82B28A00` is the command-queue producer, and a **leaf on all four paths**: no direct
calls, no indirect calls, nothing the harness cannot replay. It is the first hook here that
needs no skip counter, so its divergence figure covers every call it saw.

Selectors 0, 1 and 2 append a record whose first word is the consumer's own address and whose
length that consumer implies — 20 bytes for `EVENT_PLAY`, 8 for `EVENT_STOP`, 12 for
`EVENT_SUBMIT`. Those three sizes and handler addresses were derived here from the producer's
`lis`/`addi` pairs and match the three consumers read independently, which is a real
cross-check rather than a restatement. The derivation is `static_assert`ed against the
consumer addresses, so a misread of the lifted body fails the build.

Any other selector does not touch the queue. It asks whether the packet at `params+4` is
still live — walking the submitted-packet FIFO at `+0x148` through `next` at `+0xC`, the same
list `EVENT_STOP` unlinks, then the 20-entry table at `+0x54`, where a hit only counts as live
when its discriminator byte is not 2 — and writes a constant plus the NaN payload
`0x7FF7FFF1` into the caller's params.

**Measured, 2026-09-11: 6,706 comparable calls, zero register and zero memory divergence,
zero skipped.** The strongest result in the project so far — and the total on its own would
overstate it. A complete per-selector census, from recording every comparison of one session
rather than sampling:

| selector | what it does | calls |
|---|---|---|
| 0 | append a 20-byte `EVENT_PLAY` record | **1** |
| 1 | append an 8-byte `EVENT_STOP` record | **1** |
| 2 | append a 12-byte `EVENT_SUBMIT` record | 1,678 |
| 3+ | query whether a packet is live; writes the caller's params | 5,026 |

Three queries per submitted packet almost exactly, and the headline figure is roughly three
quarters query path. **The play and stop appends run once each** — written, built, and
exercised by a single call apiece, so a promotion runs them for real on all but one input that
nothing has checked.

An earlier version of this table read `stop = 0`, and recorded an open question about who else
could be enqueueing stop records. **Resolved: nothing else does.** Those figures came from the
periodic log lines, which print at milestones and ~10 s intervals, and the last sample read was
at 1,541 submits — before the stop happened. The complete recording caught what sampling
missed, which is a caution about every "never ran" in this document that rests on a sampled
counter rather than an exhaustive one.

The leftover off-by-one is the useful part. The appends total **1,680** while the consumer
vectors in the same session sum to **1,679** (`EVENT_SUBMIT` 1,678 + `EVENT_PLAY` 1 +
`EVENT_STOP` 0). The missing one is the stop record: **produced once, consumed once, comparable
zero times.** That discrepancy is the signature of `EVENT_STOP`'s uncomparability, not a
counting error.

The ordering fix from `docs/command-queue.md` is deliberately **not** in this port. The
producer publishes the write offset at `+204` before storing the handler and payload, which is
bug 1, and reproducing it exactly is what makes the body comparable at all: a fix would
diverge from the original by construction, and the harness cannot tell an intended behaviour
change apart from a porting mistake. The fix lands as its own change, against a verified body.

### What the buffer-pair functions will cost

`sub_82B7F828` (buffer-pair init, 76 lines) screens clean — its only callee, `sub_82F52040`,
is a 98-line leaf confirmed to be `memset` (byte fill to alignment, `rlwimi` splat, a 16-byte
unrolled `stw` loop, then 4-byte and byte tails). But it `memset`s **two caller-supplied
buffers of caller-supplied length**, and `kMaxWatch` is 64 KB across all windows, with the
overflow path dropping the offending window *and every window after it*. Since a write outside
the windows is never rewound, an under-covered port would leak native writes into the live
game rather than merely under-verify. So the lengths get measured before any native body is
written — the same check that `EVENT_STOP` taught, applied before writing instead of after.
A measurement-only hook does that: it runs the original and records both lengths, their
maxima and their null counts against the 64 KB budget, comparing nothing.

**Measured, 2026-09-11: it passes, with about 100x headroom.** First call `(192, 196)`, maxima
`(400, 256)` over a session, sum 656 against 65,536. Neither pointer was ever null, and the
function is called tens of times per session — milestones fired at 1 and 16 and never at 256 —
so unlike `REQUEUE` it does arrive. The suspicion that it would fail gate 2 was wrong, and
recording it as disqualified would have written off a portable function on an inference.

**Ported and verified, 2026-09-11: 222 comparable calls, zero register and zero memory
divergence.** Both observed size combinations — `(192,196)` and `(400,256)` — zero budget
warnings, and the oversize guard never fired. The native body reproduces the original's store
order and calls the guest `memset` on an isolated context copy rather than substituting a host
zero-fill, so the callee's behaviour at length 0 is identical by construction rather than by my
reading of its alignment preamble.

This is the function whose gate-2 disqualification I had already written into PLAN from an
inference. It is portable, it is now the second best-exercised function in Phase 2, and the
only reason it was not written off is that the claim was downgraded to a suspicion and measured.

Re-verified with bug 3's guard in place: **226 comparable calls, zero divergence, zero guard
firings.** That is the evidence the guard is free — it sits before the hook dispatches, so the
original and the native body see identical inputs and the comparison stays meaningful, while the
clamp path itself is unexercised in the same way `ENQUEUE`'s stop-append is.

The port still carries a **self-guard** rather than trust in those maxima: they describe the
calls observed, not the function's range, and other content or worlds may pass larger buffers.
If the two lengths plus the object's 40 bytes would exceed the budget, the hook must run the
original and count the skip — because the failure mode here is not under-verification but a
native write landing outside the windows, which is never rewound and so reaches the live game.

The family passes **gate 1 transitively**, which took five levels to establish. Every path
bottoms out in the two confirmed leaves — `sub_82F52040` (`memset`) and `sub_82F52B30`
(`memcpy`, 681 lines, `dcbt` prefetch and an unrolled word loop):

```
sub_82B7F8A8 -> sub_82B7F998 -> sub_82B7FE30 -> sub_82F52B30 (memcpy leaf)
             |               \- sub_82B7FB40 -> sub_82B7FE30
             |                                \- sub_82B7FC70 -> sub_82B7F7A0 -> memcpy leaf
             |                                                 \- sub_82B7FE30
             \- sub_82B7F828 -> sub_82F52040 (memset leaf)
```

No indirect calls anywhere in it, so the family's only open gate is the window budget. Worth
noting what that cost to learn: `sub_82B48440`, in the same PLAN bullet, dies two levels down
at `sub_82B49280`'s two indirect calls. A one-level screen would have passed both.

## `REQUEUE` — the first function to pass every gate and still teach nothing

`sub_82B48B28` is the scheduler's entry requeue, and it passes all three screening gates,
which no other candidate in this bullet does. It is a leaf. It is deterministic. And every
address it writes derives from state readable *before* the call — it moves a node from the
list headed at `bucket+16` to the one at `bucket+20`, where `bucket = scheduler + (state << 5)`
and the node's neighbours are read before they are overwritten — so the hook enumerates at
most six windows totalling about 40 bytes, against a 64 KB budget. No window was ever dropped:
zero budget warnings across every session.

**Measured, 2026-09-11: zero comparable calls, in two sessions.** The native body is written
and builds, the override is present in the binary (`nm` confirms `T sub_82B48B28`), and the
function was never called. The second session drove the pad specifically to reach it — thirteen
injected inputs, pushes and a trick, after gameplay settled — and `ENQUEUE` logged 6,709 calls
in that same session, so the harness was live throughout. The scheduler simply never requeued
anything.

Recorded as unverified, and not pursued further: the rule was fixed before the second result
came in, so that a third and fourth input variation could not be rationalised afterwards.

Two qualifications worth keeping, because they are what make this honest rather than tidy:

- "Never called" is a claim about **these sessions**, not about the function. Pushing a board
  for thirty seconds is not the same as exercising the audio scheduler.
- It cannot be checked against the Phase 0a trace. `sub_82B48B28` is in the 1,693-function
  corpus, absent from every table in `docs/execution-trace.md` — and that document names only
  63 distinct functions out of the 789 it reports as executed, while the per-session traced
  sets were not preserved. So whether the trace reached it is **unknown and not retrievable**,
  only re-derivable by another traced session.

So `EVENT_STOP` and `REQUEUE` are unverified for opposite reasons, which is a useful pair to
keep in mind: the first arrives constantly and is never comparable, the second would be
perfectly comparable and never arrives. Passing the gates buys nothing if the game does not
call the function.

## A window whose length arrives too late: `sub_82B7F8A8`

The buffer-pair *measure* function is gate-1 clean — the whole family is, five levels down to
`memset` and `memcpy` leaves — and it still cannot be windowed. The reason is new, and sharper
than `sub_82B482F8`'s:

```
  stwu r1,-224(r1)            ; its own frame
  ten zeroing stores          ; scratch at r1+80 .. r1+116
  bl sub_82B7F998(r3, r1+80)  ; the callee FILLS that scratch
  lwz r29,112(r1)             ; read back out of it
  lwz r27,92(r1)
  add r5,r29,r27              ; <- a length, computed from what the callee wrote
  bl sub_82F52040(r30, 0, r5) ; memset the caller's buffer, THAT long
  bl sub_82B7F828(r1+128, r30, r29, r11+r30, r27)
  bl sub_82B7F998(r3, r1+128)
```

`sub_82B482F8` fails gate 2 because the **set of addresses** is data-dependent. This one fails
because a window's **length is not knowable before the call**: `r5` is `r29 + r27`, and both
come out of the stack scratch that `sub_82B7F998` fills *during* the call. To size the window,
the hook would have to run the callee first — which is the one thing it cannot do, since
running the original is what it is trying to bracket.

Note what is *not* the problem. The stack frame is enumerable: the hook knows `r1` at entry, so
the scratch sits at `r1-224+80` and the pair at `r1-224+128`. Being stack-local is no obstacle.
The obstacle is purely the ordering — a length that exists only after the work has happened.

Its transitive written set also absorbs the `sub_82B7F998` -> `sub_82B7FB40` -> `sub_82B7FC70`
-> `memcpy` subtree, which would have to be read and bounded before any port. So the buffer-pair
family splits: `sub_82B7F828` (init) is portable and measured, and `sub_82B7F8A8` (measure) is
not a harness target.

So gate 2 has two distinct failure modes, and both were found by reading bodies rather than by
screening callees:

| mode | example | why |
|---|---|---|
| address set data-dependent | `sub_82B482F8` | walks a list of unknown length, three objects patched per node |
| window length arrives during the call | `sub_82B7F8A8` | `r5 = r29 + r27`, both written by a callee |
| address set discovered mid-call | `sub_82B7F998` | writes through `r11` as it is loaded and advanced, plus `sub_82B7FB40`'s unbounded subtree |

With that, every function in PLAN's Phase 2 bullet list is screened:

| function | outcome |
|---|---|
| `sub_82B28CC0` `EVENT_SUBMIT` | **promoted**, 1,678 calls clean |
| `sub_82B28A00` `ENQUEUE` | **6,706 calls clean** — but play=1, stop=0 |
| `sub_82B7F828` buffer-pair init | **222 calls clean** |
| `sub_82B28B78` `EVENT_PLAY` | 1 call clean, one input point |
| `sub_82B48B28` `REQUEUE` | passes all three gates, **0 calls** |
| `sub_82B28C18` `EVENT_STOP` | gate 1 — live decoder, 0 comparable |
| `sub_82B48A50`, `sub_82B48530`, `sub_82B48440` | gate 1 — indirect calls (the last two levels down) |
| `sub_82B1F7E8` | gate 3 — `mftb` |
| `sub_82B482F8`, `sub_82B7F998`, `sub_82B7F8A8` | gate 2 — unwindowable |

Three verified, one promoted, and eight that the harness cannot check or the game does not call.
That ratio is the honest shape of Phase 2, and it was not visible from the function list.

## Recorded vectors, and the read set the harness never had

Phase 4 tier 1 wants identical inputs fed to the verified C++ **and** to the Rust port, compared
byte for byte. Rather than generate vectors, the harness now records the real ones:
`skate3_audio_vectors_path` (with `skate3_audio_vectors_max`) writes one line per comparison —
the entry registers, the read set, and the write set with both its entry bytes and the bytes the
**original lifted body** produced. `probe/harness/run_session.sh` takes `AUDIO_VECTORS_PATH`.

Building that exposed a gap in the harness worth stating on its own: **`windows` is a
specification of what a function *writes*, not what it *reads*.** Windows exist to be
snapshotted, rewound and compared. But a consumer reads its command record to find the player,
the producer reads the system pointer and the ring base, and `EVENT_PLAY` reads the source
pointer — none of which are written, so none appeared in any window. The first replay attempt
failed on **every single vector** with "no segment covers this address", at the first *read*
rather than at any comparison. `ShadowCompare` now takes a separate `inputs` span, declared at
each of the six call sites; it is never snapshotted, rewound or compared.

### The replay, and what its green actually covers

`rust/skate-audio-core/examples/replay_vectors.rs` rebuilds guest memory from each vector — each
span its own segment, because a real vector puts an object at `0x7018E110` on the stack and its
buffers at `0x401736D0` on the heap, 768 MB apart, which no flat window can hold. Nothing is
invented: an address the function reaches that was not recorded leaves the vector
**unreplayable**, never zero-filled, because feeding the port fabricated inputs turns a failure
into a meaningless pass.

**Measured 2026-09-11: every vector of a complete session replays. 8,607 of 8,607 pass —
0 disagreements, 0 skipped, 0 unreplayable, 0 partial.** (An earlier capped run gave 2,048 of
2,048; raising the cap to 40,000 recorded the whole session instead of its first ~8 seconds.)

| function | result | what that is worth |
|---|---|---|
| `ENQUEUE` | 6,706 pass | Fully compared, including the query path's constant — see the bijection below. **0 of 5,026** query vectors recorded a non-empty FIFO, so `packet_is_live`'s list-walk branch is untested — see below, it is now a permanent limit rather than a pending one. |
| `EVENT_SUBMIT` | 1,678 pass | A large share verify the `packet→next` write **vacuously**: on an empty FIFO that word is already 0 on entry and 0 in the expectation, so the write is a no-op. In the capped run it was 391 of 398. |
| `EVENT_PLAY` | 1 pass | one input point, as ever |
| `BUFPAIR` | 222 pass | `sub_82B7F828` ported to `buffers.rs`. Substantive rather than vacuous: the object's entry bytes are real stack garbage (`00000184`, `00FF0000`, `FFFFFFFF`) and the expected bytes decode exactly to the ten words the port writes |
| `EVENT_STOP` | 0 vectors | it never reaches `ShadowCompare`, even though the producer demonstrably enqueued one stop record in the same session |

### The list-walk branch is unreachable, not merely untested

`packet_is_live` walks the FIFO before scanning the table, and **no recorded query has ever
arrived with a non-empty FIFO**: 0 of 1,173 in the capped run, then 0 of 5,026 across a complete
session — a 4.3x larger sample. The ENQUEUE hook's read set was extended to capture a bounded
8-node FIFO prefix precisely so such a vector would be replayable rather than `unreplayable`;
it has never had one to prove itself on. Bounded at 8 deliberately: an unbounded walk is the
gate-2 problem that makes `sub_82B482F8` unwindowable.

Recorded as a **permanent** limit of what these sessions can drive, not a pending task. The
stopping rule was fixed before the second sample came in, the same rule that correctly ended the
`REQUEUE` chase, so that a third cap raise and a fourth macro could not be rationalised after
the fact.

### The green is only meaningful because a control failed

The first negative control **did not fail**: removing the `packet→next` clear from the Rust
`event_submit` still reported 398/398, for exactly the reason above — it attacked the one write
whose recorded before and after are identical. A test that cannot fail proves nothing, and for a
few minutes this one could not.

Two controls against spans where entry genuinely differs from expected do fail, and their
partitions are the evidence rather than the failures themselves:

- Wrong FIFO head: `pass=7 fail=391`, at `40C219B8+3 expected 20, got 30`. The 7 survivors are
  precisely the non-empty-FIFO vectors, which take the `else` branch and never write the head.
- Wrong handler word: `pass=1173 fail=400`, at `4B3B9D50+3 expected 78, got 7C`. The 1,173
  survivors are precisely the query vectors, which write no handler.

Both partitions match the span-shape census taken independently from the recording. Restoring
both returned the sources byte-identical and the green with them.

Two more controls, added with the later ports:

- **`BUFPAIR`, wrong first length:** `pass=0 fail=76` at `7018E110+11 expected C0, got C1` —
  byte 11 is the low byte of `first_len` at `+0x08`, 192 perturbed to 193.
- **Liveness inverted in `packet_is_live`:** `pass=791 fail=782`.

### The query path's constants, and a partition that nearly fooled me

The non-append path writes one of two `.rdata` floats, read directly by the original from
`0x82165A10`/`0x8231A844`, so neither value appears in any window. Copying them out of the
expected bytes to compare against those same bytes would be using the answer to check the
answer. Instead: compute liveness independently in Python from each vector's recorded table,
and check it partitions the observed constants into exactly two consistent values. It does —
**live → `00000000` (0.0f), not live → `3F800000` (1.0f)**, 391 against 782, zero exceptions.

That is a *bijection* argument, not a measurement of the image: it cannot say which value the
image calls "live". What it does license is supplying both to the replay, which then tests that
Rust's `packet_is_live` agrees with the independent Python scan on all 1,173 — two
implementations, not one checked against itself. Claim that and nothing more.

Note the values invert what the names suggest: the *live* constant is 0.0 and the *gone*
constant is 1.0. Alongside the `0x7FF7FFF1` NaN stamped into `params+8`, that reads like a
completion fraction — 0.0 for a packet still queued, 1.0 for one that is gone — but that is an
inference from two numbers, not a finding.

**The lesson is in the liveness control's partition.** I first explained its 791/782 split by
assuming the survivors were the live vectors, and the arithmetic refused to close. Counting the
1,173 query vectors directly gives **391 / 391 / 391**: table-found with `disc != 2`,
table-found with `disc == 2`, and not found at all. The inversion reaches only the 782
*table-found* vectors and flips both classes into failure, while the 391 *not-found* ones fall
through unchanged and keep passing — so failures are 782 and passes are 400 append + 391
not-found = 791, exactly as observed. Three buckets of identical size made two different
explanations numerically indistinguishable. Reasoning from totals could not separate them;
counting could.

That census also explains the ~3 liveness queries per submitted packet noticed earlier: the
`wanted` addresses step by `0x10` and the *same* address appears in different buckets
(`4016AF40` as both found-live and found-dead), so it is one sweep re-probing packets as their
state changes, not three identical queries.

Still true of the harness: windows must cover every byte a function writes, because a write
outside them keeps the lifted value while the native body runs. `lr`, `ctr`, `xer`, `fpscr`,
`msr` and the reservation state are not compared. Another thread writing a watched window
during the rewind would read as a divergence; not seen so far.

## The capture tap

The guest mixer's output reaches the host through one import. `sub_82F10980` copies the
mixer's interleaved buffer into a planar stack buffer (`r1+1888`, which is why every session
logs the same first-submit address, `0x7006E730`) and passes it to
`XAudioSubmitRenderDriverFrame`. The host driver only `memcpy`s it.

The SDK lives in `librexruntime.so`, so defining `__imp__XAudioSubmitRenderDriverFrame` in
the executable takes over every guest call site. The tap copies the frame, then forwards to
the runtime's own implementation through `dlsym(RTLD_NEXT)`. No SDK change was needed.

`mixdiff.py` assumes the layout, so reading a file back only shows the file is readable.
`check_capture.py` tests the layout from the signal instead:

| session | mode | silent submits | peak | roughness planar / interleaved | seam ratio |
|---|---|---|---|---|---|
| `p1_movies` | shadow | 1,822 | 0.6602 | 0.122 / 0.529 | 0.71 |
| `p1_fixed` | shadow | 1,825 | 0.6602 | 0.124 / 0.536 | 0.63 |
| `p1_native` | native | 1,824 | 0.6602 | 0.135 / 0.522 | 1.57 |

All 4,000 submits, 0 non-finite samples in each. Read as planar, the audio is roughly four
times smoother than read as interleaved. Steps across submit boundaries look like steps
inside a submit, so no submit was dropped or reordered. `mixdiff.py` reads `p1_movies` and
`p1_fixed` back as EXACT.

## SIGFPE: host float work inside a guest call

The first version of the tap killed the game at exactly the 4,000th submit. Under gdb, with
the cap moved to 2,000, it died at the 2,000th instead:

```
Thread "Audio Worker" received signal SIGFPE
#0  CloseLocked(char const*)                 divsd (%r15,%rcx,1),%xmm1
#1  __imp__XAudioSubmitRenderDriverFrame
#2  sub_82F10980
#3  rex::runtime::FunctionDispatcher::Execute
#5  rex::audio::AudioSystem::WorkerThreadMain
```

The fixed tap logs the control word it finds on entry: **MXCSR `0x0000`** — every FP
exception unmasked. The division of `submits × 256 / 48000.0` was inexact, and trapped.

The SDK already knows about this. `AudioSystem::WorkerThreadMain` re-masks after the guest
callback returns, with a comment that "the FPSCR emulation leaks MXCSR state". Hooks run
**inside** that callback and get no such protection. `0x0000` is exactly what
`disableFlushModeUnconditional()` writes from a zero `fpu_csr`, and every initialisation path
sets the mask bits, so the worker thread's guest FPSCR state was most likely never
initialised. That last part is inference; the fault site and the control word are measured.

**Rule:** host-only float work in a hook masks exceptions around itself and restores the
guest's control word on exit (`FloatExceptionsMasked` in `skate3_audio_dump.cpp`). Native
DSP replacements are different: their float work *is* the guest's, and has to run under the
guest's own mode.

## Captures are not reproducible run to run

Three sessions booted the same way, aligned at their first non-silent submit:

| pair | first audio | identical aligned submits | first difference |
|---|---|---|---|
| `p1_fixed` vs `p1_movies` (both native off) | 1162 / 1162 | 2,054 of 2,838 | submit 49 |
| `p1_fixed` vs `p1_native` | 1162 / 1174 | 2,196 of 2,826 | submit 253 |
| `p1_movies` vs `p1_native` | 1162 / 1174 | 2,040 of 2,826 | submit 49 |

Between the two native-off sessions, the first differences are tiny: 1e-15 to 1e-19, against
0.0 or other tiny values. Those are normal floats, not denormals, so this is not a
flush-to-zero difference. Later differences are full scale: 435,869 differing samples are at
least 1e-3. At the one submit tested, a whole-channel shift of up to ±48 samples does not
explain them. **The cause is not established.**

Two consequences:

1. **Cross-session captures cannot verify promotion.** The native-on session falls inside the
   band between two native-off sessions. That is consistent with promotion changing nothing,
   and proves nothing more. The shadow harness is what proves `EVENT_SUBMIT`.
2. **PLAN Phases 4 and 6 assume reproducibility the recomp does not have.** Both want a
   capture that "matches bit-for-bit" for the same scene or trigger. Before that criterion
   means anything, either the source of the nondeterminism has to be found — thread timing,
   random variation, streaming — or the comparison has to happen within a single process.

## Build costs, measured

| change | cost |
|---|---|
| `CMakeLists.txt` | reconfigure plus 261 build steps, mostly SDL3's C files |
| a harness source file | 1–3 compiles plus relink, 3–4 s |
| `generated/skate3_init.h` (the trace hook) | 127 objects, 195 s — `docs/environment-linux.md` |

## Files

| file | what |
|---|---|
| `recomp/src/skate3_audio_shadow.{h,cpp}` | the harness |
| `recomp/src/skate3_audio_native.cpp` | the queue producer, `EVENT_SUBMIT`, `EVENT_STOP`, `EVENT_PLAY`; three modes each |
| `recomp/src/skate3_audio_dump.cpp` | the `audio_dump_path` tap |
| `recomp/src/skate3_audio_probe.cpp` | XMA feed probe, unchanged |
| `probe/harness/run_session.sh` | one session |
| `probe/harness/check_capture.py` | layout check from the signal |
| `probe/harness/crash.gdb` | stop on SIGFPE with a backtrace |

The recomp's demo-path change (`skate3_demo_path_play_movies`) lives only in the recomp,
because it is not an audio file.
