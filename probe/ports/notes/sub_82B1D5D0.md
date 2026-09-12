# sub_82B1D5D0

- Role: leaf, `s32 f(obj*)`. A ramp: moves the f32 `value` (+0) toward the s32 `target` (+24)
  by `steps * rate`, clamps at the target, and returns `value` rounded half away from zero. It is
  slot 29 of the op table at guest 0x82FD3600 (pointer found at 0x82FD3674 in the image dump),
  so it has no direct `bl` site. The same table holds verified ports D198 (36), D700 (30) and D790 (31).
  154,787 calls per boot on `RwAudioCore Dac`.
- Object (r3). Nothing in `docs/rw_audio_structs.h` names it: `+0 f32 value`, `+4 f32 rate`,
  `+8 s32 last_target`, `+12 s32 last_duration`, `+16 s32 duration`, `+20 s32 steps`, `+24 s32 target`.
- Flow:
  1. Return the target early when `float(target) == value`.
  2. Re-derive when the target or duration changed:
     - store `last_target` and `last_duration`;
     - if `duration <= 0`, snap `value` to the target and return the target;
     - otherwise `rate = ((target - value) / duration) * G * U`, where G = [0x830775D8] and
       U = [0x822F890C] = 1/4096.
  3. `value = fmadds(steps, rate, value_at_entry)`. If `rate < 0` and the new value is below the
     target, or `rate >= 0` (or NaN) and it is above the target, clamp `value` to the target.
  4. Reload `value`: `< 0` takes `fsubs 0.5`, anything else (NaN included) takes `fadds 0.5`,
     then `fctiwz`. r3 gets the low word, zero-extended.
- Stores, in order: `stw obj+8`, `stw obj+12` (re-derive only); `stfs obj+0` (duration <= 0, then
  return) or `stfs obj+4` (rate); `stfs obj+0` (fmadds); `stfs obj+0` again when clamped. The
  `std`/`stfd` at -16(r1) go to its own red zone and are not windowed.
- Windows: `write(obj, 16)` on every path, a superset because bytes left unwritten compare
  equal. Reads cover `obj+16..+27` and the four singles (0x830775D8, 0x822F890C, 0x82165A10 = 0.0,
  0x8209975C = 0.5). It is always enumerable, so Windows() returns true.
- Result: r3 on every path. On an early return it holds the zero-extended target from `lwz r3,24(r3)`.
  Mask `kReturnR3`, the same as the table's other ops.
- Gates: gate 1 passes (leaf, no imports, no indirect calls, no lock), gates 2 and 3 pass (no
  timebase), and gate 4 passes on r3.
- Unsure:
  - G at 0x830775D8 is a runtime global, stored by `sub_82B1E290` as an int times f1 times a
    single. It reads 0.0 in the image dump, which was probably taken before it was set. The body
    loads it live, so its value never enters the port.
  - The comparisons follow `cr.compare(double,double)` (NaN clears lt/gt/eq), which is exactly C++
    `<`, `>` and `==`.
  - The `fmadds` operand order (f7, f11, f13) is kept for NaN propagation.
