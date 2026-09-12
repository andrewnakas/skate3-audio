# sub_82B2F8C0

Lifted: `skate3_recomp.67.cpp:43461`, 742 lines. 30,433 calls during boot on `RwAudioCore Dac`.
One block of a Dac object's surround output chain. `r3` = the ~1104-byte object, `r4` = a pair of
buffer descriptors at `+28` / `+32`.

## Shape

1. State `+1092` exactly 3: `sub_82B2F798(object)`, then `+1092 = 4`.
2. Level `+52` not greater than the rodata zero at `0x82165A10` (NaN included, `bgt` is ordered):
   memset one 1024-byte block per `+42` channel of `[pair+28]`, `+1092 = 0`, return 1.
3. Four parameter pairs (`+52/+352`, `+60/+356`, `+68/+360`, `+1100/+348`). All equal: straight to
   the reconfigure. Any differ and `+1092` is 0: clear the channels, `+1092 = 1`,
   `sub_82B2F590(object)`, return 1. Any differ and `+1092` is non-zero: `+1092 = 1`, continue.
4. Reconfigure: take 3072 bytes off `[[object+8]+32]` and write the reduced pointer back; wire six
   mix stages (filters at `+484` stride 36, records at `+700` stride 60) and up to `[+1089]` output
   stages (filters at `+72` stride 24, records at `+144` stride 60). Each filter gets its two entry
   points, each record gets `+4` = its filter, `+8` = the one shared scratch block, `+28` = 768.
5. Run all six mix records through `sub_82B3D8E0` (record 0 with flag 0, 1..5 with flag 1), swap
   the pair's two descriptors, then per `+42`: run one output record per speaker group and copy the
   block channel 0 holds into each channel that group feeds -- 1 for stereo; 1, 3, 2 for four; 2, 4,
   (6), 1, 3, (5) for the 6/8 case, which then memsets channel 5 (layout 6) or 7 (anything else).
6. Swap the descriptors back, restore the scratch pointer from the value saved in step 4, then
   `sub_82B2F590(object)`, return 1.

## Stores

| address | size | note |
|---|---|---|
| `object+1092` | 4 | `4`, `0` or `1` depending on the path |
| `holder+32` | 4 | twice: `top-3072`, then `top` again at the end |
| `object+484 + 36*i`, `+0`/`+4`, i<6 | 4 each | `0x82B39FA0` / `0x82B3A038` |
| `object+700 + 60*i`, `+4`/`+8`/`+28`, i<6 | 4 each | filter, scratch, 768 |
| `object+72 + 24*i`, `+0`/`+4`, i<[+1089] | 4 each | `0x82B38B68` / `0x82B61BB8` |
| `object+144 + 60*i`, `+4`/`+8`/`+28`, i<[+1089] | 4 each | filter, scratch, 768 |
| `pair+28`, `pair+32` | 4 each | swapped, then swapped back: net unchanged |
| `r1-160` | 4 | own frame; the `__savegprlr_23` spills are inside it |

The four stored words are all real function addresses, each checked against a `DEFINE_REX_FUNC` in
the lifted tree, not assumed: `sub_82B39FA0` (mix dispatcher), `sub_82B3A038` (zeroes a gain),
`sub_82B38B68` (allpass-stage dispatcher), `sub_82B61BB8` (a bare `blr`). They go into a record's
`+4` object, whose `+0` is the pointer `sub_82B3D8E0` calls through (`kObjMixer`/`kMixerEntry`
there) -- so this function is what arms that indirect call.

## Gate verdict

**gate-1 at depth 1.** `sub_82B3D8E0` is called eight to eleven times per block and its two `bctrl`
(0x82B3DA00, 0x82B3DA8C) go through the pointer this function just stored. `sub_82B32870.inc`'s
reasoning applies: a replay would run the mixer kernel twice over the same ring. The other callees
are benign (`sub_82EE5E80` is memset, `sub_82EDF460` is memcpy, both confirmed from the lifted
bodies; `sub_82B2F590` and `sub_82B2F798` both pass gate 1). `Windows()` returns false.

Gate 2 would pass, at about 70 spans of 4 bytes -- over the 32-span budget unless the six mix
groups are coalesced into one span each (`+484..+688` and `+700..+1032` are contiguous runs), which
would bring it to about 8. The census marks 7 stores `gate2_suspect`, all of them the two loop
families, whose counts are `[+1089]` (readable at entry) and the constant 6.

## Uncertainties

- `+60`, `+68` and `+1100` are only known as "floats compared against a cached copy". Only `+52`
  has a use here (a level: at or below zero the output is silence).
- Every memset/memcpy is a fixed 1024 bytes while the channel stride is `4*[desc+14]`, so the two
  only line up when the descriptor's frame count is 256. Nothing checks it.
- `[+1089]` has no visible bound, but the geometry gives one: output filter *i* sits at `+72+24i`
  and record 0 at `+144`, so a count above 3 would have the filters overwrite the records.
  Reproduced without a clamp either way.
- Three `addi` results in the reconfigure block (`object+880`, `+940`, `+1000`) are dead --
  materialised record addresses the scheduler never used. Not reproduced; they write nothing.
- Group 0 of the mix-stage loop stores `+28` before `+8` where the other five store `+8` first.
  Preserved, with the `if (stage == 0)` in the body; the addresses are distinct and nothing reads
  them in between, so it is a scheduling artifact rather than a semantic one.
