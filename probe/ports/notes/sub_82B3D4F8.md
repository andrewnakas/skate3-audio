# sub_82B3D4F8 — mix dispatcher over a six-pointer buffer descriptor

Lifted: `skate3_recomp.68.cpp:9763`, 76 lines. Thread `RwAudioCore Dac`, boot 174,693 calls.
Void; no stores of its own outside its frame. Two callees, both leaf VMX kernels:
`sub_82B3CF58` (one gain) and `sub_82B3D0A8` (two gains).

## Arguments

- `r3` gain block: `+16` and `+20` singles (`sub_82B39FA0` reads the same object at `+16..+32`).
- `r4` sample count, passed to either kernel in `r3` — and left in `r4` as well, because the
  original never reassigns it. Neither kernel reads `r4` on entry.
- `r7` descriptor: `+0` addend (y), `+4` source (x), `+8` selector, `+12` extra, `+16` mixed
  output (z), `+20` copy output (w).

## Paths

`selector == 0`: `sub_82B3CF58(n=r4, y=desc[0], x=desc[4], z=desc[16], w=desc[20], f1=gain0)`.
Writes z and w, four bytes per sample each.

`selector != 0`: `sub_82B3D0A8(n=r4, r5=desc[20], r6=desc[0], r7=desc[4], r8=selector,
r9=desc[12], r10=desc[16], stack 84(r1)=desc[20], f1=gain0, f2=gain1)`. The stack argument is
real: `sub_82B3D0A8` opens with `lwz r30,84(r1)` and never does its own `stwu`, so it reads the
slot out of this function's frame. `desc[20]` therefore goes across twice, in `r5` and on the
stack; reproduced, not tidied.

## The frame is reproduced, deliberately

`stw r12,-8(r1)` (frame + 88) and `stwu r1,-96(r1)` (the back chain) are this call's own frame
and are not windowed, but the frame has to exist: it carries `84(r1)`, and `sub_82B3CF58` also
writes its gain splat at `r1-128..r1-113` relative to the `r1` it is handed. `r1` is set to
`entry - 96` before either call and restored with `addi r1,r1,96` after, then `lr` is reloaded
from the slot exactly as the epilogue does.

## Windows

- `selector != 0` returns **false**. `sub_82B3D0A8` is 662 lines with eight `stvx128` and nine
  `stfsx` into six buffers, every base a loop cursor plus an inter-buffer delta computed inside
  the call (18 gate-2 suspects in its census). Its write set is not derivable from here. A
  guessed superset is not an option: the harness replays the callee a second time on rewound
  memory, so any byte it writes outside the windows is written twice against the live game with
  no rewind — and whether that is idempotent depends on facts about those 662 lines that nobody
  has established. **Lift this by mirroring `sub_82B3D0A8`'s own `Windows()` once its port
  lands**, exactly as the `selector == 0` path mirrors `sub_82B3CF58`'s.
- `selector == 0` returns true: two write spans for the vector body (`z` and `w` from their
  16-byte floor, `64 * (n/16)` bytes, only when `x` is 16-byte aligned) and two for the scalar
  tail (`4 * (n - 16*(n/16))` bytes at the exact base). Copied from `sub_82B3CF58`'s port, whose
  derivation of the `stvx128` address masking distributing out of the loop is the load-bearing
  part.
- `n <= 0` returns true with no spans: the kernel's `bge` leaves before any store. That call
  compares only the ABI-preserved registers — vacuous, but not wrong, and the same hole exists
  in `sub_82B3CF58`'s own port.

## Gates

Gate 1 pass (both callees are leaves: no lock, allocation, import, indirect call or timebase).
Gate 2 on the `selector != 0` path only, as above. Gate 3 pass. Gate 4: void, so the mask is
`kReturnNone`; `r3` after the call holds whatever the kernel left, produced by the same code in
both runs, so nothing is gained by comparing it. STATUS `pending`.

## Unsure

- Whether `desc[8]` is a count, a channel-pair flag or a mode. It is passed on to
  `sub_82B3D0A8` in `r8` as a value, so it is more than a selector there.
- `desc[12]` ("extra") is only used by the two-gain kernel; nothing here shows what it points at.
