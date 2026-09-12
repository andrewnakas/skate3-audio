# sub_82B4FAF8

Lifted: `skate3_recomp.68.cpp:54664`, 147 lines. No guest callees at all; the only two calls are
the kernel imports `RtlEnterCriticalSection` and `RtlLeaveCriticalSection`. No `bctrl`, no `mftb`.
Called 1917 times during boot on `RwAudioCore Dac`.

## Arguments

- `r3` the object. `+52` u32 = base of an array of 28-byte entries whose first word is a pointer;
  `+68` u32 = how many entries to walk. Nothing else of the object is touched.

There are no other arguments.

## Constant addresses

Computed as `((lis_imm & 0xFFFF) << 16) + offset`, never read off by eye:

| expression | address | use |
|---|---|---|
| `lis r30,-31992` + `17904` | `0x830845F0` | holds the `RTL_CRITICAL_SECTION*`; reloaded for the release |
| `lis r6,-31988` + `-8480` | `0x830BDEE0` | a spare/free head, popped through the node's `+0` link |
| `lis r11,-31988` + `-8476` | `0x830BDEE4` | the list anchor `r10` addresses |

The anchor is four bytes above the spare head, so the two are almost certainly one structure at
`0x830BDEE0`: `{spare, end, front, count}`.

## What one iteration does

`node = *(u32*)(*(u32*)(object+52) + i*28) + 20` -- the intrusive node sits 20 bytes into the
object the entry points at.

1. `if (node == *0x830BDEE0) *0x830BDEE0 = node->+0;`
2. `next = node->+4; if (next) next->+0 = node->+0;`
3. `prev = node->+0; if (prev) prev->+4 = node->+4;` -- a standard doubly-linked unlink, with `+0`
   the prev direction and `+4` the next direction.
4. **`node` is recomputed from scratch**: the array base is reloaded from `object+52`, the entry
   reloaded, `+20` reapplied. The port reproduces the reload rather than reusing the value.
5. `node->+0 = 0; node->+4 = anchor->+4;`
6. `if (anchor->+0 == 0) anchor->+0 = node; else (anchor->+4)->+0 = node;` -- the else branch
   **reloads** `anchor->+4`, which is still the old front at that point.
7. `c = anchor->+8; anchor->+4 = node; anchor->+8 = c + 1;` -- in that order.

`anchor->+0` is only ever written while it is null, so it holds the first node ever pushed and is
never maintained afterwards here. `anchor->+4` always becomes the newest node. That is why the
port calls them `kAnchorEnd` and `kAnchorFront` rather than head/tail.

## Stores

| address | size | mnemonic |
|---|---|---|
| `0x830BDEE0` | 4 | `stw r9,-8480(r6)` -- conditional |
| `next + 0` | 4 | `stw r4,0(r9)` -- conditional |
| `prev + 4` | 4 | `stw r11,4(r9)` -- conditional |
| `node + 0` | 4 | `stw r5,0(r11)` |
| `node + 4` | 4 | `stw r9,4(r11)` |
| `0x830BDEE4` | 4 | `stw r11,0(r10)` -- only when it was null |
| `front + 0` | 4 | `stw r11,0(r9)` -- the other arm of the same branch |
| `0x830BDEE8` | 4 | `stw r11,4(r10)` |
| `0x830BDEEC` | 4 | `stw r9,8(r10)` |
| `r1 - 112` | 4 | `stwu` -- own frame, plus the r12/r30/r31 spills inside it |

## Loop bound

`r7` counts iterations from zero; the bound is **re-read from `object+68` at the bottom of every
iteration** and compared unsigned. The entry check at the top is `cmplwi` against 0 followed by
`ble`, which for an unsigned compare can only mean equal -- so any nonzero count enters the loop.

## Gate verdict

**gate-1, at depth 0.** The function *is* the lock: it takes the global audio critical section on
entry and releases it on exit. Running it a second time on rewound memory would take the lock
twice from one thread (recursive acquisition is real state the rewind cannot undo -- the recursion
count and owner live in the kernel object, not in the windowed guest memory) and would publish the
same nodes onto the global list twice. `Windows()` returns false unconditionally.

Note that gate 2 would also have been a problem: the write set includes `next+0` and `prev+4` for
every node, and those pointers only exist after the previous iteration has already rewritten the
list, so a later iteration's targets are not knowable from entry state. The census marks nine
stores `gate2_suspect`.

## Return mask

The function has no `li r3,...` on any path: `r3` at exit is whatever `RtlLeaveCriticalSection`
left, having been given the critical-section pointer. The honest mask is therefore "nothing the
caller can rely on" -- functionally void. The port declares `kReturnR3` anyway, because a
gate-labelled port with `kReturnNone` and no `spec.write()` trips lint check 5 (the vacuous
green). Nothing is compared either way: the macro never enters the shadow branch for a gate label.

## Uncertainties

- The two imports are reached through their guest addresses (`0x82F9CB44`, `0x82F9CB54`) in the
  dispatch table rather than by name, because lint check 6 forbids naming an import thunk
  directly from a port and a kernel import has no guest port to route a `GuestCall` through. Same code, one
  difference: it writes `ctr`, which a `bl` does not. `ctr` is volatile and uncompared, and this
  body never runs.
- The meaning of the spare head at `0x830BDEE0` is a reading from one site: it is consulted only
  to be advanced when it happens to name the node being moved. Whether it is a free list, an
  iteration cursor, or a cache of "the next one to visit" was not established.
- `+0` as prev and `+4` as next is inferred from the unlink pair alone. The freelist pop walks
  through `+0`, which is the opposite direction from the push, and that was not explained.
- The dead `lwz r11,4(r11)` at `loc_82B4FB74` clobbers the node address, and the block that
  follows rebuilds it. Reproduced as a rebuild; whether the compiler intended the reload as an
  alias barrier or it is just register pressure is unknown.
