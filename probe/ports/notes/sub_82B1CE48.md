# sub_82B1CE48

- Role: leaf `u32 f(obj*)`. Clears the slot `+4*(s16[+2]+2)`; then, if `0 < s32[+4] <= u8[+0]`,
  copies `u32[+8]` into slot `+4*(depth+2)` and records the low half of `s32[+4]` in `s16[+2]`.
  Returns `u32[+12]`. 46 lifted lines, no callees, imports, indirect calls, timebase or locks.
  53,535 boot calls on `RwAudioCore Dac`. Address neighbour of sub_82B1CE18 (same +0 u8 capacity
  / +4 s32 depth test), so it reads as another method on that object. Nothing in
  `docs/rw_audio_structs.h` names it.
- Argument: r3 = object pointer.
- Stores, in order: `stwx` 0 to `obj + ((u32)(s16[+2]+2) << 2)`, 4 bytes (the 32-bit shift wraps
  below the object for s16 < -2, as in the original); then on the taken branch only: `stwx`
  `u32[+8]` to `obj + 4*(depth+2)`, 4 bytes (depth 1..255, so +12..+1028); `sth` low 16 of a
  RELOADED `s32[+4]` to `obj+2`, 2 bytes.
- Aliasing kept: the first store can land on +0, +4, +8 or +12, so every load after it stays
  after it; +4 is reloaded before the `sth` and +12 after the stores, as lifted.
- Windows: the first slot from the entry s16. The branch is predicted by replaying the first
  store: the depth reads as 0 if the store lands on +4, the capacity as 0 if it lands on +0 (both
  not taken), otherwise the entry values. When taken, `{obj+4*(depth+2), 4}` and `{obj+2, 2}`.
  At most three spans, 10 bytes. Reads `{obj, 16}`. Overlapping spans are allowed by the harness.
- Result: r3 = `u32[+12]` zero-extended (`lwz`). Mask `kReturnR3`. No direct call site
  exists (only skate3_init/register list it), so it is reached through a function pointer.
- Gates: 1 pass (leaf), 2 pass (enumerable from entry memory, predicted as above), 3 pass, 4 pass.
- STATUS: pending. Unsure: only whether the aliasing cases (s16[+2] in -2..1) ever occur in play;
  the rewrite and the prediction cover them either way.
