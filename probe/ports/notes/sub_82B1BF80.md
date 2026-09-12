# sub_82B1BF80

- Role: leaf take-and-clear accessor over +0: `r3 = u32 [obj+0]; [obj+0] = 0`. Direct sibling of
  sub_82B1BF68, which does the same to +16. 13 lifted lines, no callees, imports, indirect calls,
  timebase or locks. 64,662 boot calls on `RwAudioCore Dac`.
- Argument: r3 = object pointer. Nothing in `docs/rw_audio_structs.h` identifies the object, so
  the offset stays plain `+0`.
- Store: one, `stw r10,0(r11)` (r10 = 0, r11 = entry r3), 4 bytes at `obj+0`, provenance `entry`.
  Load and store hit the same word, so load-then-clear is load-bearing and `object` is captured
  before r3 is overwritten by the loaded value.
- Result: r3 = the old word, zero-extended to 64 bits (`lwz`), as the lifted line leaves it.
  Mask `kReturnR3`. No `sub_82B1BF80(ctx` call exists in the lifted tree (only
  skate3_init/register list it), so every call arrives through a function pointer and the ABI
  return register is all a caller can consume. Scratch r10/r11 are not reproduced.
- Windows: write `{obj, 4}`, read `{obj, 4}`; known from entry registers with no loads. Always true.
- Gates: 1 pass (leaf), 2 pass (single entry-relative store), 3 pass (no mftb), 4 pass (r3).
- STATUS: pending. The `.inc` predates this note (written by an earlier run); it was re-read
  against the lifted body and left unchanged. Unsure of nothing that affects the rewrite.
