# sub_82B4FC00

- Role: `void f(system*, u32 sample_rate)` — (re)program every hardware XMA context the System
  owns. It stores the second argument at `u32[system+0x50]`, then walks the `rw_xma_stream` array
  at `u32[system+0x34]` for `u32[system+0x44]` elements of stride `0x1C` and, per element, builds a
  56-byte `XMA_CONTEXT_INIT` on its own stack and issues six kernel calls on that stream's context.
  180 lifted lines, **no guest callees**, six imports, no indirect call, no timebase, no lock.
  1,907 boot calls on `RwAudioCore Dac` (tier D) — the same count as `sub_82B32870`, which is
  consistent with one pass per voice teardown/setup cycle.
- The structures are already documented: `rw_xma_stream` in `docs/rw_audio_structs.h` (array at
  System `+0x34`, count at `+0x44`, stride `0x1C`, `channels` at `+0x18`, `context` at `+0x00`
  pointing at `{id, in_buf0, in_buf1, out_buf, work_buf}`), and `XMA_CONTEXT_INIT` is the kernel's
  own 56-byte struct (`third_party/rexglue-sdk/src/kernel/xboxkrnl/xboxkrnl_audio_xma.cpp:109`),
  so every field name in the port is borrowed, not invented.
- The block it builds at `r1+80`, field by field (the whole 56 bytes are zeroed first, **every
  iteration**, by seven `stdu r9,8(r11)`; `+44..+55` is `XMA_LOOP_DATA` and stays zero):

  | field | value |
  |---|---|
  | `input_buffer_0_ptr` | `u32[context+4]` (`rw_xma_stream.source`'s context twin) |
  | `input_buffer_0_packet_count` | 1 |
  | `input_buffer_1_ptr` | `u32[context+8]` |
  | `input_buffer_1_packet_count` | 1 |
  | `input_buffer_read_offset` | 32 — **bits**, one XMA packet header, matching `docs/xma-transcode.md` |
  | `output_buffer_ptr` | `u32[context+12]` |
  | `output_buffer_block_count` | 24 |
  | `work_buffer` | `u32[context+16]` |
  | `subframe_decode_count` | 4 |
  | `channel_count` | `u8[stream+0x18] - 1` |
  | `sample_rate` | the r4 argument |

  The kernel reads `channel_count` as `is_stereo = channel_count >= 1`, which is a second
  confirmation of the `-1` that `docs/rw_audio_structs.h` already records. The decrement is
  `addi r10,r10,-1` on a zero-extended byte, so a stream claiming 0 channels stores `0xFFFFFFFF`;
  the port reproduces that rather than clamping.
- **New, and worth carrying forward:** the r4 argument is the value the kernel copies into the
  context's `sample_rate`, and the same word is parked at `u32[system+0x50]`. So `+0x50` is the
  System's current XMA sample rate (or rate index — `XMA_CONTEXT_DATA.sample_rate` is a small
  enumerated field in the hardware register block, not Hz), and this function is how a rate
  change is pushed to every context. `docs/rw_audio_structs.h` does not name `+0x50` yet.
- Stores: exactly **one** outside this call's own frame — `stw r4,80(r3)`, 4 bytes, unconditional,
  before the loop. Everything else is the 208-byte frame: the `stwu` back chain, the
  `__savegprlr_24` spills, and the 13 words of the init block (`+80..+120`, plus the seven
  8-byte clears covering `+80..+135`).
- Reads: `u32[system+0x44]` (twice per iteration — once as the entry guard, once reloaded at the
  bottom), `u32[system+0x34]` (**reloaded before every one of the six calls**, because the imports
  clobber the volatile file), `u8[stream+0x18]`, and `u32[stream+0]` — reloaded **five** separate
  times inside the store block and once per call after that. All of those reloads are reproduced;
  they are not hoistable, because the imports can write guest memory.
- Result: **none.** No `li r3,...` on any path; r3 is left holding whatever the last import
  returned (`XMAEnableContext`'s status), or, when the count is zero, the System pointer it
  arrived with. The macro line carries `kReturnR3` because a gate-labelled port with a false
  `Windows()` and `kReturnNone` trips lint check 5 (a vacuous comparison); the mask is never read,
  since the macro does not arm the shadow branch for a gate label. A comparable version would
  declare `kReturnNone` and `spec.write(r3 + 80, 4)`.
- Gate 1 **fails at depth 0** and cannot be salvaged on any path (the only path that avoids the
  imports is the zero-stream one, which writes a single word and does nothing else). The six
  imports — `XMADisableContext`, `XMAInitializeContext`, `XMASetOutputBufferValid`,
  `XMASetInputBuffer0`, `XMASetInputBuffer1`, `XMAEnableContext` — each reprogram decoder hardware
  and, through `XMAInitializeContext`, translate guest pointers to physical addresses and
  memset the 64-byte `XMA_CONTEXT_DATA` register block. None of that is rewindable.
- How the imports are called: through the **guest address** each thunk is registered at
  (`REX_CALL_INDIRECT_FUNC(0x82F9CC44)` and friends). `generated/skate3_init.cpp` maps
  `0x82F9CC04/24/34/44/54` and `0x82F9CCC4` to exactly the six thunks the `bl`s target, and all
  six fall inside `[REX_CODE_BASE, REX_CODE_BASE + REX_CODE_SIZE)`, so the indirect dispatch
  resolves to the same `PPCFunc*` the direct branch would. This is also the only way to write the
  body without naming a kernel symbol directly, which lint check 6 forbids.
- Unsure: nothing about the field mapping — it is pinned by the kernel struct. What is *not*
  established is whether `+0x50` holds Hz or the 2-bit rate index; reading the caller that supplies
  r4 would settle it and was not done here. The literal 24 output blocks pairs suggestively with
  `rw_xma_stream.out_cursor` wrapping at `0x1800`, but the units of `output_buffer_block_count`
  were not chased, so that is a coincidence worth one check, not a conclusion.
