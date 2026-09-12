# sub_82B1C4B8

- Role: leaf `u32 f(obj*)`, a stepping cursor over a 24-byte object. If `s32[+20]` lies in
  `[s32[+0], s32[+4]]` it returns `+20` untouched. Otherwise, if `s32[+16] > 0`, it adds the
  signed byte `+12` to `+8`; past `+4` it wraps to `+0` (and returns `+0` directly); below `+0`
  it wraps to `+4`. It returns `+8` (reloaded). 60 lifted lines, no callees, imports, indirect
  calls, timebase or locks. 61,606 boot calls on `RwAudioCore Dac`. Nothing in
  `docs/rw_audio_structs.h` names the object. Address neighbour of sub_82B1C778, whose object
  also has bounds at +0/+4 and a value at +20; whether they are the same type is not established.
- Argument: r3 = object pointer.
- Stores: up to two per call, all `stw` to `obj+8`, 4 bytes: the stepped value, then `+0` (over
  the top) or `+4` (under the bottom). The stepped value is always stored first, as lifted.
- Arithmetic: `extsb` + 64-bit `add` with a zero-extended u32, and only the low word is stored and
  compared (`cmpw`), so the rewrite's u32 wrap-add is identical. All compares are signed.
- Result: r3 = the probe (in range), the low bound (`rotlwi r3,r7,0`), or the `+8` reload. Each
  is a zero-extended u32. Mask `kReturnR3`. No direct call site exists (only skate3_init/register
  list it), so it is reached through a function pointer.
- Windows: write `{obj+8, 4}` unconditionally; read `{obj, 24}`. Always true.
- Gates: 1 pass (leaf), 2 pass (single entry-relative word), 3 pass (no mftb), 4 pass (r3).
- STATUS: pending. Unsure: the asymmetric wrap (over the top returns `+0` directly, under the
  bottom returns the stored `+4` via reload) is reproduced as lifted. The results agree either
  way, so nothing turns on it.
