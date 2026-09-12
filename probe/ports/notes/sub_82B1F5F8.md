# sub_82B1F5F8

Lifted: `skate3_recomp.67.cpp:3760`, 154 lines. Callees `sub_82B1BE30`, `sub_82B1F440`, plus one
`bctrl` of its own. No imports, no `mftb`. Called 3097 times during boot on `RwAudioCore Dac`.

## Arguments

- `r3` the object, the only argument. `+8` u32 = the device object (has a vtable at its `+0`);
  `+14` u8 = record count; `+15` and `+17` u8 = two independent copy-back flags; `+28` = the first
  of `count` 12-byte state records.

## The 12-byte state record

| offset | type | use |
|---|---|---|
| `+0` | u8 | identifier, passed to `sub_82B1BE30` as `r4` |
| `+4` | s32 | the value last pushed to the device |
| `+8` | s32 | the value that should be pushed |

The loop is a dirty flush: for each record, if `+8 != +4` (signed compare, equality only), call
`sub_82B1BE30(device, +0, +8)` and then copy `+8` over `+4`. The `+8` word is **reloaded after
the call** rather than reused, so the callee is allowed to have changed it.

The loop bound is **re-read from `object+14` at the bottom of every iteration** and compared
signed against a zero-extended byte; the cursor advances by 12 on both arms. Entry is guarded by a
separate read of the same byte against zero (unsigned), so a zero count skips the loop entirely --
and leaves the cursor at `object+28`.

## The device query

```
device = *(u32*)(object+8)
device->vtable[20](device, 11, r1+80)
```

`r4` is 11 and the function afterwards reads exactly eleven words out of the buffer (`r1+80`,
`+84`, `+88`, then `+92`..`+120`), so the literal is the buffer's word count. The frame is
reproduced for this reason: the buffer is passed by address and has to be inside the 160 bytes the
`stwu` claims.

- `out[0] == 0` (signed): call `sub_82B1F440(object)` and return **its** result -- there is no
  `li r3,...` on this path.
- otherwise: the copy-backs below, then `r3 = 1`.

## Copy-back

The destination is the record *just past* the array: `tail = object + 28 + 12*iterations`, which
is `object+28` when the loop never ran.

- `object+15 != 0`: `tail+4 = out[2]; tail+0 = out[1];` -- in that order, high word first. This
  arm also moves the eight-word destination to `tail+8`.
- `object+17 != 0`: eight words from `out[3..10]` to `dest+0..dest+28`, where `dest` is `tail+8`
  if the first arm ran and `tail` otherwise -- so a clear `+15` lets the eight-word block
  overwrite the two words the first arm would have written.

All eight loads precede all eight stores in the original (`r10,r9,r8,r7,r6,r5,r4,r3`, then the
`stw`s in the same order), so the port keeps them as two separate passes over a local array
rather than one interleaved loop.

## Stores

| address | size | mnemonic |
|---|---|---|
| `record + 4` | 4 | `stw r11,4(r31)` -- once per dirty record |
| `tail + 4` | 4 | `stw r10,4(r31)` |
| `tail + 0` | 4 | `stw r9,0(r31)` |
| `dest + 0..28` | 8 x 4 | `stw r10/r9/r8/r7/r6/r5/r4/r3,0..28(r11)` |
| `r1 - 160` | 4 | `stwu` -- own frame, plus the `__savegprlr_29` spills inside it |

The out buffer at `r1+80..123` is written by the indirect callee, inside this call's own frame.

## Gate verdict

**gate-1, at depth 0, three times over.**

1. Its own `bctrl` at `0x82B1F66C` goes through the device's vtable slot 20. The target is not
   knowable from entry state without trusting the vtable, and whatever it is, it is the device
   query -- it reads hardware or driver state, so a replay returns different words.
2. `sub_82B1BE30` contains six indirect calls of its own (census).
3. `sub_82B1F440` is the object re-initialiser.

`Windows()` returns false unconditionally.

Gate 2 would have failed as well, for a reason worth recording: the eight-word destination
depends on `object+15`, which is readable from entry state, but the *tail address* depends on how
many iterations the loop ran, and the loop bound is re-read from memory that `sub_82B1BE30` could
change. The census marks all eleven stores `gate2_suspect`.

## Return mask

`kReturnR3`. Both exits leave a result there: `li r3,1` on the copy-back path, and on the
`out[0] == 0` path whatever `sub_82B1F440` returned, passed straight through. That is the honest
mask -- unusually, r3 is genuinely meaningful here, unlike most of the gate-1 batch.

## Uncertainties

- The vtable slot-20 entry was not chased; "device query" is read off the shape of the call
  (a word count and an out buffer) and the use of `out[0]` as a validity flag, not from the
  callee.
- `+15` and `+17` are two independent flags with no established meaning. The fact that a clear
  `+15` makes the eight-word block land on top of the two words the other arm writes suggests the
  tail record has two different layouts, but only this one site was read.
- Whether `tail` is a real twelfth record, a scratch area, or the start of a different structure
  is unknown. It is written past the last record the loop touched, and nothing here bounds it.
- `+4` and `+8` are compared signed (`cmpw`) even though the test is equality; the port keeps the
  signed compare in case a future reader assumes unsigned.
