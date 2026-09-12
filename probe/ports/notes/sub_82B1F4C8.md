# sub_82B1F4C8

Lifted: `skate3_recomp.67.cpp:3589`, 170 lines. Callees `sub_82B1BE30`, `sub_82B1F440`, plus one
`bctrl` of its own. No imports, no `mftb`. Called 514 times during boot on `RwAudioCore Dac`.

The sibling of `sub_82B1F5F8`: same object, same record array, same two callees, same
`sub_82B1F440` failure path. This one **opens** the device; that one refreshes it.

## Arguments

- `r3` the object. `+0` u32 = a config object; `+14` u8 = record count; `+28` = the first 12-byte
  state record.
- `r4` a descriptor: a signed halfword at `+0`, a raw byte at `+2`, six bytes at `+3..+8` that go
  into the argument block each shifted up one byte, and a full word at `+8` (the same offset,
  read a second time -- big-endian, so the byte read is that word's high byte).

## Constant address

`lis r10,-32003` -> `0x82FD0000`, `lwz r3,13816(r10)` -> **`0x82FD35F8`**, computed as
`((imm & 0xFFFF) << 16) + offset`. A null there is the first failure path.

## The open call

```
config = *(u32*)(object+0)
table  = *(u32*)(config+64)
index  = (s16)desc[0..1] + 3                  // SIGNED: a negative index reaches below the table
entry  = *(u32*)(table + ((index*4) & ~3))    // 32-bit wrapping sum
singleton->vtable[0]( singleton,
                      entry + table,          // 64-bit add; the carry reaches the callee
                      desc[2],
                      r1+96,                  // six words: desc[3..8] each << 8
                      *(u32*)(config+72),
                      *(u32*)(config+76) + *(u32*)(desc+8),   // 64-bit add
                      r1+80 )                 // {record count, record array pointer}
```

`rotlwi rX,rX,8` on a zero-extended byte is exactly `byte << 8` -- the source is at most `0xFF`,
so nothing rotates out of bit 31. The port writes the shift and says why.

`r1+88` and `r1+92` sit between the two blocks and are **never written**, so the callee sees
whatever the frame held there. The frame is reproduced for the usual reason: both blocks are
passed by address.

The store order in the original is 96, 104, 100, 80, 108, 112, 116, 84 -- not ascending. Kept.

## Result of the open

The handle is tested with `cmplwi`, i.e. on the **low word only**.

- zero: `sub_82B1F440(object)` then `li r3,0`.
- nonzero: push every record, then `r3 = handle`.

## The push loop

The cursor is biased by -8 (`addi r31,r31,-8`), which is why the offsets read `+8`, `+12`, `+16`
for the record's `+0`, `+4`, `+8`:

```
sub_82B1BE30(handle, u8 record+0, u32 record+8)
record+4 = *(u32*)(record+8)      // RELOADED after the call
cursor += 12
```

Unlike `sub_82B1F5F8`'s loop this is **unconditional** -- there is no `+8` versus `+4` compare, so
every record is pushed on an open. The bound is re-read from `object+14` at the bottom of every
iteration (not the copy stored at `r1+80`) and compared signed against a zero-extended byte.

## Stores

| address | size | mnemonic |
|---|---|---|
| `r1+96,100,104,108,112,116` | 6 x 4 | the shifted descriptor bytes |
| `r1+80` | 4 | the record count |
| `r1+84` | 4 | `object+28`, the record array pointer |
| `record + 4` | 4 | `stwu r10,12(r31)` -- once per record |
| `r1 - 208` | 4 | `stwu` -- own frame, plus the `__savegprlr_23` spills inside it |

Everything but the record words is inside this call's own frame.

## Gate verdict

**gate-1, at depth 0.** Its own `bctrl` goes through the singleton's vtable slot 0 and is a device
open: it allocates or acquires whatever the handle names. Replaying it on rewound memory would
open a second device and leak the first, which is the textbook case the gate exists for.
`sub_82B1BE30` independently carries six indirect calls, and `sub_82B1F440` is the
re-initialiser. `Windows()` returns false unconditionally.

Gate 2 would in fact have been fine on the failure path and nearly fine on the success path: the
census marks only one store `gate2_suspect`, because every other store is frame-relative. The
record walk is the exception -- its length is re-read from `object+14` inside the loop.

## Return mask

`kReturnR3`, and here it is genuinely load-bearing: the caller gets the device handle or zero.
This is the one function in this batch whose `r3` means something.

## Uncertainties

- The vtable slot-0 target was not chased. "Device open" is read from the call's shape (a
  descriptor, a table entry, two out/in blocks by address, a handle back, and a
  re-initialise-and-return-zero failure path), not from the callee.
- `+8` of the descriptor is read twice, once as a byte into the shifted block and once as a word
  added to `config+76`. That is either a packed field being used two ways or a compiler
  coincidence; it was not resolved, and both reads are reproduced.
- The `+3` bias on the signed halfword index is unexplained. Because the halfword is
  sign-extended, a descriptor index of -3 selects `table[0]` and anything below that reads before
  the table. Nothing here bounds it.
- What `config+72` and `config+76` are was not established; they are passed straight through.
- `r1+88`/`r1+92` being skipped inside a block passed by address suggests the block is really two
  fields at `+80`/`+84` and a separate structure, or that the callee ignores those words. Not
  resolved.
