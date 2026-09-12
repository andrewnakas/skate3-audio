# sub_82B1D3D0

Leaf, 300 lines, 52,680 calls per boot, `RwAudioCore Dac`. One argument: r3 = an oscillator
object. Returns the current sample in r3 as a rounded int.

Layout read from this function alone (nothing in `docs/rw_audio_structs.h` names it):
`+0` u8 waveform selector, `+4` f32 phase, `+8` s32 period in update ticks, `+12` s32 amplitude.
A period `<= 0` returns 0 immediately and writes nothing.

Body: `increment = kUpdateDelta / (float)period`; then `while (!(phase < kPhaseWrap)) phase -=
kPhaseWrap`, storing each iteration. Then the waveform: **0** scales the phase into table units,
rounds half away from zero, truncates, and takes bits 9:8 as a quadrant and 7:0 as an index into
a 256-entry u16 quarter table at `0x82FD36B8` — quadrants 1 and 3 read the table backwards from
`+512`, quadrants 2 and 3 negate — then `sample * amplitude * kSineNorm`; **1** is a pulse,
`phase < kRoundHalf ? 0 : amplitude`; **2** is a ramp, `phase * amplitude`; **>= 3** is a triangle,
`(phase < half ? phase : kPhaseWrap - phase) * amplitude * kTriangleGain`. The phase then advances
by `increment` and is stored, and the sample is rounded half away from zero and truncated into r3.

Write set: `{osc+4, 4}` and nothing else — one span, declared unconditionally, since the
early-return path writes nothing and an untouched byte compares equal. The `fcfid`/`fctiwz`
spills at `r1-16` are the function's own red zone, so they are not windowed. `kReturnR3`.
Reads: the 16-byte header, the four entry constants, plus the table-units factor, the whole
514-byte table window and the normaliser on waveform 0, or the gain on waveform >= 3.

Gates: 1 pass (leaf, no imports, no indirect calls, no lock), 2 pass (one fixed-offset store),
3 pass (no timebase; output is a function of entry state and memory), 4 pass (r3). STATUS pending.

Exactness points, in the order they are easy to get wrong:

- The eight pool addresses were each computed as `((imm & 0xFFFF) << 16) + offset`. Three of them
  (`kUpdateDelta` 0x830775D8, `kRoundHalf` 0x8209975C, `kZeroFloat` 0x82165A10) are addresses the
  already-verified ports use, which is independent confirmation of the arithmetic.
- At `loc_82B1D588` the `fsubs f8,f12,f13` subtracts the phase from **f12, still the wrap constant
  loaded at entry**, not from the round-half constant in f10. Reading f12 as the nearer load would
  make the triangle's falling edge wrong only for a non-1.0 wrap value.
- The wrap loop uses `bge` on `fcmpu`, so a NaN or infinite phase spins forever. The original does
  the same; it is reproduced rather than guarded, and 52,680 calls a boot never hit it.
- Both round-half sites branch on `blt`, so an unordered compare takes the *add* side. Written as
  `if (x < zero) sub else add`, which matches C++'s NaN result.
- The `disableFlushModeUnconditional()` calls sit at the same points as the lifted body,
  including the one *inside* the wrap loop and the one only on the negative round-half side.

Unsure: `+8` is called a period because it divides `kUpdateDelta`, and `+12` an amplitude because
it scales every waveform; the constants' *values* were not read out of the image (no image dump on
this box), so `kPhaseToUnits` is only inferred to be 1024.0 from `srawi 8` + `clrlwi 24` selecting
a quadrant and a 256-entry index, and `kPhaseWrap` inferred to be 1.0 from the same reading.
Nothing in the port depends on those inferences — only the names do.
