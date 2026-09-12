# sub_82B21AC0

The audio worker thread's pump. 378 lifted lines, **one call per boot** — it does not return until
the pump is told to stop, so the call count is the thread's lifetime, not a workload.
`RwAudioCore Dac`. Its only caller is `sub_82B21D70`, which throws the result away.

Argument: r3 = the worker object. `r27 = u32(r3+8)` is the system object `sub_82B48530` drains, and
`u32(queue+92)` is the critical section held for the whole pump.

Shape: mirror the run state, take the lock, then an outer loop that waits on `u32(self+96)` through
`sub_82EDFEC0(handle, -1)`, and an inner loop that runs until the fill buffer is no longer free:
- mirror 0 — drain the command queue, nothing else.
- mirror 1 — stamp `kProfileStart`, drain, and (only if the *request* is still 1) fill the current
  buffer with `sub_82B219E8`; anything but a 1 back means silence, so all 6144 bytes at
  `u32(self+84) + index*6144` are zeroed by `sub_82EE5E80`. Then mark the buffer filled and hand
  every filled buffer to the device — vtable `+100` for the status block on the frame, and while
  its second word is 2 or fewer (unsigned), vtable `+84` with the 36-byte descriptor at
  `self + 100 + 36*index`. Both indices wrap at 2 with a second store of zero, never a modulo.
- anything else — fall straight through.

Then: charge `now + (total - start)` into `kProfileTotal`; reconcile the mirror with the request,
where **2 is the state in which the lock is not held** (a mirror of 2 re-acquires, a request of 2
releases); and go round again while the request is 1 and the next fill buffer is free.

Globals, all recomputed from the `lis` immediates: `0x830845CC` (the run state, which
`sub_82B218E8.inc` already names `kRunState` and sets to 1 or 2), `0x830845C8` (this loop's mirror),
`0x8306705F` (the u8 "keep running" flag — eight bytes past `sub_82B218E8`'s `kArmedByte`, a
different cell), and `0x830BDEBC` (`sub_82B219E8.inc`'s `kProfile`, whose `+4` and `+8` are used
here as a stopwatch).

**Correction:** `probe/ports/notes/sub_82B21D70.md` gives this function's global as `0x82044588`,
from "`lis -31992` -> 0x82040000". Both halves are wrong: `((-31992 & 0xFFFF) << 16)` is
`0x83080000`, and `0x82040000 + 17864` would be `0x820445C8`, not `0x82044588`. The values in this
port are the arithmetic, and they agree with `sub_82B218E8.inc` and `sub_82B219E8.inc`, which
reached the same cells independently.

Stores: `kRunStateMirror` u32 (twice per pass at most), `kProfileStart` u32, `kProfileTotal` u32,
`self+88` and `self+92` u32 (each up to twice per pass, the wrap), and the two slot words at
`self+172`/`self+176` via `stwx`. Frame-internal: the status block at `r1+80` (written by the
device) and the `stwu` back chain.

The structure is reproduced with two `for(;;)` loops and one `stop` flag. The flag is not cosmetic:
three paths jump to `loc_82B21D50` **without** re-reading the running byte that `loc_82B21D44`
tests, and another thread can change that byte in between, so collapsing the two exits would be a
real behaviour change.

Gate verdict: **gate 1**, for two independent reasons at depth 0 — it takes and releases
`RtlEnterCriticalSection`/`RtlLeaveCriticalSection` itself at four call sites, and it calls the
device through `u32(u32(self+76)+0)+100` and `+84` (`bctrl` at 0x82B21C14 and 0x82B21C60). Replaying
it on rewound memory would take the lock a second time, re-submit buffers to the real audio device,
and consume the same command queue twice. It is **also gate 3**: `sub_82B1F7E8` is the timebase read
(`sub_82B219E8.inc` is labelled gate-3 for exactly that), so two of the stores here are
time-dependent by construction. Both imports are reached through their dispatch-table addresses
(0x82F9CB44 / 0x82F9CB54) rather than the `__imp__` symbols, the convention `sub_82B4FAF8.inc` set,
because lint check 6 forbids naming a thunk from a port body.

Windows() returns false, and here it is not close: the device's two vtable methods write through
pointers this call hands them, the submit loop's trip count depends on what the device reports, and
the whole thing blocks on an event. Result mask `kReturnR3` is a formality — there is no `li r3` on
any path, so r3 is whatever the last call left, and the one caller overwrites it with zero.

Unsure: `self+172` is inferred from `(index + 43) * 4` with an index that is only ever 0 or 1, so
only two of those words are ever touched; whether the array is longer is unknown. The two vtable
slots are named from their arguments (`+100` fills a block, `+84` takes a descriptor and a zero);
nothing here reads the status block except its second word.
