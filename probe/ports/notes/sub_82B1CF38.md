# sub_82B1CF38

- Role: leaf `u32 f(obj*)` returning the signed maximum of `s32 [obj+0]` and `s32 [obj+4]`.
  On a tie it returns the +4 word (the `blelr` path), which is the same value. 15 lifted lines, no
  callees, imports, indirect calls, timebase or locks. 40,042 boot calls on `RwAudioCore Dac`.
- Argument: r3 = object pointer. Nothing in `docs/rw_audio_structs.h` names the object; offsets
  stay plain.
- Stores: none.
- Result: r3 = the winning word, zero-extended to 64 bits (both loads are `lwz`; `mr r3,r11`
  copies the zero-extended +0 value). The compare is `cmpw` on the low words, signed. Mask
  `kReturnR3`. No `sub_82B1CF38(ctx` call exists in the lifted tree (only skate3_init/register
  list it), so it is reached through a function pointer and r3 is all a caller can consume.
  Scratch r11 (the +0 word) and cr6 are not reproduced.
- Windows: no writes; read `{obj, 8}`. Always true.
- Gates: 1 pass (leaf), 2 pass (no writes), 3 pass (no mftb), 4 pass (r3).
- STATUS: pending. Unsure of nothing that affects the rewrite.
