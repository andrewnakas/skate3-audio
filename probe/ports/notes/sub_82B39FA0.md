# sub_82B39FA0 — five-gain mix dispatcher, or a buffer clear

Lifted: `skate3_recomp.68.cpp:905`, 92 lines. Thread `RwAudioCore Dac`, boot 182,370 calls.
Two callees: `sub_82B399D0` (901-line leaf kernel) and `sub_82F52040` (`memset`, confirmed in
`docs/buffer-size-bug.md`).

## Arguments

- `r3` gain block: five singles at `+16..+32`, loaded into `f1`-`f5`. `+32` is also **written**
  after the call with the kernel's returned `f1`, so it is running state, not a parameter.
- `r4` element count: the kernel's `r3`, and `count * 4` bytes on the clear path.
- `r5` an opaque word, only ever stored to `100(r1)` as an outgoing argument.
- `r7` descriptor, the same layout `sub_82B3D4F8` unpacks: `+0` addend, `+4` source, `+8`
  selector, `+16` mixed, `+20` copy.

## Paths

`selector == 0`: `sub_82B399D0(r3=r4, r4=r4, r5=r5, r6=r6, r7=desc, r8=desc[16], r9=desc[0],
r10=desc[4], f1..f5 = gains, stack 84=desc[16], 92=desc[20], 100=r5)`, then
`stfs f1,32(r31)`. Note `r7` is *not* reassigned on this path — the kernel receives the
descriptor pointer itself, unlike `sub_82B3D4F8`'s path A. `desc[16]` goes across twice, in
`r8` and at `84(r1)`.

`selector != 0`: `memset(desc[20], 0, (count << 2) & 0xFFFFFFFC)` and nothing else.

## The frame is reproduced, deliberately

`sub_82B399D0` opens with `lwz r11,100(r1)` / `lwz r26,92(r1)` / `lwz r8,84(r1)` and never does
its own `stwu`, so those three slots of this function's 128-byte frame are real arguments and the
frame has to exist for the call to mean anything. The link slot (frame + 120) and the `r31` slot
(frame + 112) are reproduced too and read back by the epilogue; the kernel's own `__savegprlr_22`
spills land below `frame`, so nothing collides. `r31` is only ever the entry value in this
rewrite — the original's `mr r31,r3` is a register the callee saves and restores, so leaving it
untouched reaches the same exit state.

## Stores

| address | size | mnemonic | path |
|---|---|---|---|
| `gains + 32` | 4 | `stfs f1,32(r31)` | selector == 0 |
| `[desc[20], + count*4)` | `count*4` | inside `memset` | selector != 0 |
| everything `sub_82B399D0` writes | — | 16 `stvx128`, 14 `stfsx`, 30 `stfs`, 16 `stw` | selector == 0 |

`84(r1)`, `92(r1)`, `100(r1)`, `-8(r1)`, `-16(r1)` and the back chain are this call's own frame,
not windows.

## Windows

- `selector == 0` returns **false**. `sub_82B399D0`'s write set is not enumerable from entry:
  56 gate-2 suspect stores, with bases that are loop cursors plus inter-buffer deltas computed
  inside the call. (One store is trivially known — the `lis`-based global at `0x830D1524`, from
  `lis r6,-31987` plus 5412 — but that is one of 56.) Over-declaring a guessed
  superset is not a safe substitute — the harness runs the callee a second time on rewound
  memory, so any byte it writes outside the windows is applied twice to the live game and never
  restored. **Lift this by mirroring `sub_82B399D0`'s own `Windows()` when it gets one**; the
  `stfs f1,32(r31)` latch is then the only span to add.
- `selector != 0` returns true with one span: `memset` writes exactly its length and nothing
  past it (byte prologue, then `n>>4` 16-byte blocks, then `(n>>2)&3` words, then `n&3` bytes —
  which sums to `n` exactly). A length over 32 KB is left to the harness's own budget check,
  which runs the original and records the oversize; a length that would wrap the map is refused
  here.
- `count == 0` on the clear path declares no span, so that call compares only the ABI-preserved
  registers. Vacuous but not wrong: nothing is written.

## Gates

Gate 1 pass on both paths (`sub_82B399D0` is a leaf; `memset` is the project's confirmed leaf —
no lock, allocation, import, indirect call or timebase anywhere in the closure). Gate 2 on the
`selector == 0` path only. Gate 3 pass. Gate 4: void, `kReturnNone`. STATUS `pending`, with the
comparable half being the clear path.

## Unsure

- The fifth single at `+32` is both read into `f5` and overwritten by the result. That reads like
  a one-pole filter's carried state, but nothing here establishes it.
- `r6` is passed through untouched because the original never assigns it. The kernel does not
  read it: its first mention is `lis r6,-31987`, which overwrites it. Checked, not assumed.
