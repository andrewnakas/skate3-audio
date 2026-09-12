// sub_82B2DBA8  role: resample one block of a stream -- carry the previous block's tail into a scratch run, append the new input, resample each channel into the destination buffer, keep the new tail, then swap the buffer pair and republish the rate   lifted: skate3_recomp.67.cpp:39040 (356 lines)
// STATUS: pending
// calls/session: boot 141508  play ?  map ?          thread: RwAudioCore Dac
// note: probe/ports/notes/sub_82B2DBA8.md
namespace port_82B2DBA8 {

// r3 = the voice. Nothing in docs/rw_audio_structs.h names it, so the offsets stay plain.
constexpr uint32_t kSystem = 8;        // rw_ptr  ->(+0) the arena whose +32 is a bump pointer
constexpr uint32_t kChannels = 42;     // u8   channel count; RELOADED at every loop test
constexpr uint32_t kRateCache = 64;    // f32  the last [stream+52] this voice was set up for
constexpr uint32_t kStep = 68;         // u32  the 16.16 phase increment handed to sub_82B43FB8
constexpr uint32_t kPhase = 72;        // u32  the 16-bit phase, in the word's LOW half here
constexpr uint32_t kTailOffset = 76;   // u16  offset into the voice of the per-channel tail rows
constexpr uint32_t kFrameCap = 78;     // u16  the most output frames one call may produce
constexpr uint32_t kTailCount = 80;    // u8   input samples carried over from the previous block
constexpr uint32_t kTailBias = 81;     // u8   samples the resampler must keep for interpolation
constexpr uint32_t kTailRowBytes = 24; // addi r24,r24,24 -- six singles of tail per channel
constexpr uint32_t kTailRowFloats = 6; // addi r21,r21,6

// r4 = the stream. Its +28/+32 descriptor pair is the shape sub_82B34E08 and sub_82B29BE0 swap.
constexpr uint32_t kPairBack = 28;     // rw_ptr  the source descriptor this call reads
constexpr uint32_t kPairFront = 32;    // rw_ptr  the destination descriptor it writes
constexpr uint32_t kFormat = 40;       // rw_ptr  ->(+12) the format's rate single
constexpr uint32_t kInputFrames = 48;  // u32  input frames in the source descriptor
constexpr uint32_t kStreamRate = 52;   // f32  the rate the voice compares against its cache
constexpr uint32_t kFormatRate = 12;   // f32  on the format

// On a descriptor -- sub_82B29AF0's kBufferBase/kChannelStride, same names, same arithmetic.
constexpr uint32_t kBufferBase = 4;      // u32  channel 0's float array
constexpr uint32_t kChannelStride = 14;  // u16  singles between one channel and the next
constexpr uint32_t kArenaTop = 32;       // u32  the bump pointer, decremented and restored here

constexpr uint32_t kFrameBytes = 224;    // stwu r1,-224(r1)
constexpr uint32_t kIndexSlot = 80;      // addi r6,r1,80 -- sub_82B43FB8's cursor, own frame
constexpr uint32_t kPhaseSlot = 84;      // addi r7,r1,84 -- sub_82B43FB8's phase, own frame
constexpr uint32_t kBlockSlack = 151;    // addi r6,r9,151
constexpr uint32_t kBlockAlign = 0xFFFFFF80u;  // rlwinm r5,r6,0,0,24
constexpr int32_t kStepFreeFrames = 8192;      // li r25,8192 when the step is zero

// __savegprlr_17 / __restgprlr_17: the fifteen callee-saved words this function spills into its red
// zone around the three guest calls, held in locals instead. The harness compares r13-r31, so their
// entry values have to come back on both exits.
struct SavedGprs {
  PPCRegister values[15];
  void capture(const PPCContext& c) {
    values[0] = c.r17;  values[1] = c.r18;  values[2] = c.r19;  values[3] = c.r20;
    values[4] = c.r21;  values[5] = c.r22;  values[6] = c.r23;  values[7] = c.r24;
    values[8] = c.r25;  values[9] = c.r26;  values[10] = c.r27; values[11] = c.r28;
    values[12] = c.r29; values[13] = c.r30; values[14] = c.r31;
  }
  void restore(PPCContext& c) const {
    c.r17 = values[0];  c.r18 = values[1];  c.r19 = values[2];  c.r20 = values[3];
    c.r21 = values[4];  c.r22 = values[5];  c.r23 = values[6];  c.r24 = values[7];
    c.r25 = values[8];  c.r26 = values[9];  c.r27 = values[10]; c.r28 = values[11];
    c.r29 = values[12]; c.r30 = values[13]; c.r31 = values[14];
  }
};

double LoadSingle(uint8_t* base, uint32_t addr) {  // lfs
  PPCRegister temp{};
  temp.u32 = REX_LOAD_U32(addr);
  return double(temp.f32);
}

void StoreSingle(uint8_t* base, uint32_t addr, double value) {  // stfs
  PPCRegister temp{};
  temp.f32 = float(value);
  REX_STORE_U32(addr, temp.u32);
}

// rlwinm rX,rY,2,0,29 -- the low word shifted left two with the bottom two bits cleared, held in a
// 64-bit register. Every `add` that consumes one of these is 64-bit on zero-extended operands, so a
// carry into bit 32 survives in the register and only the store or the callee's addressing drops
// it: the intermediates below stay uint64_t for that reason.
inline uint64_t Scale4(uint64_t value) {
  return uint64_t(uint32_t(uint32_t(value) << 2) & 0xFFFFFFFCu);
}

// mullw rN,rStride,rIndex ; rlwinm ; add -- one channel's float array, the same three instructions
// as sub_82B29AF0's ChannelAddress. mullw is the 64-bit product of two SIGN-extended words.
inline uint64_t ChannelAddress(uint64_t stride, uint64_t index, uint64_t buffer_base) {
  const int64_t elements = int64_t(int32_t(uint32_t(stride))) * int64_t(int32_t(uint32_t(index)));
  return Scale4(uint64_t(uint32_t(elements))) + buffer_base;
}

REX_FUNC(Native) {
  const uint32_t voice = ctx.r3.u32;   // mr r31,r3
  const uint32_t stream = ctx.r4.u32;  // mr r19,r4

  // __savegprlr_17 spills r17-r31 and lr into the red zone and both exits restore them. There is no
  // __savefpr here -- the body uses only f0 and f13.
  SavedGprs saved;
  saved.capture(ctx);

  // stwu r1,-224(r1). Reproduced -- most ports skip their own frame -- because r1+80 and r1+84 are
  // sub_82B43FB8's cursor and phase slots and that callee spills into its own red zone below r1.
  // Without the allocation both would land in the caller's live frame, outside every window.
  const uint32_t entry_sp = ctx.r1.u32;
  REX_STORE_U32(entry_sp - kFrameBytes, entry_sp);
  ctx.r1.u32 = entry_sp - kFrameBytes;
  const uint32_t frame = ctx.r1.u32;

  ctx.fpscr.disableFlushModeUnconditional();
  const double rate = LoadSingle(base, stream + kStreamRate);   // lfs f0,52(r4)
  const double cached = LoadSingle(base, voice + kRateCache);   // lfs f13,64(r3)

  // fcmpu cr6,f0,f13 ; beq cr6 -- an unordered compare (a NaN rate) takes this path, which is what
  // C++ `!=` does with a NaN operand. Nothing is resampled: the rate is cached, the stream's rate is
  // reset from the format, and the call returns 1.
  if (rate != cached) {
    StoreSingle(base, voice + kRateCache, rate);              // stfs f0,64(r3)
    const uint32_t format = REX_LOAD_U32(stream + kFormat);   // lwz r11,40(r4)
    ctx.r3.s64 = 1;                                           // li r3,1
    // The load is after the store above, as in the original; the two could alias in principle.
    StoreSingle(base, stream + kStreamRate,
                LoadSingle(base, format + kFormatRate));      // lfs f0,12(r11) ; stfs f0,52(r4)
    ctx.r1.u32 = entry_sp;  // addi r1,r1,224
    saved.restore(ctx);     // __restgprlr_17
    return;
  }

  // loc_82B2DBE8 -- take a scratch run off the arena's bump pointer: a block of
  // ((4*input_frames + 151) & ~0x7F) bytes, published at [arena+32] for the duration of the call and
  // restored from r17 at the end.
  const uint32_t system = REX_LOAD_U32(voice + kSystem);               // lwz r8,8(r31)
  const uint64_t input_frames = REX_LOAD_U32(stream + kInputFrames);   // lwz r10,48(r19)
  const uint64_t carried_in = REX_LOAD_U8(voice + kTailCount);         // lbz r11,80(r31)
  const uint64_t input_bytes = Scale4(input_frames);                   // rlwinm r9,r10,2,0,29
  const uint64_t available = carried_in + input_frames;                // add r22,r11,r10
  const uint32_t arena = REX_LOAD_U32(system + 0);                     // lwz r7,0(r8)
  const uint64_t slack = input_bytes + kBlockSlack;                    // addi r6,r9,151
  const uint64_t block = uint64_t(uint32_t(slack) & kBlockAlign);      // rlwinm r5,r6,0,0,24
  const uint32_t arena_top = REX_LOAD_U32(arena + kArenaTop);          // lwz r17,32(r7)
  const uint64_t scratch = uint64_t(arena_top) - block;                // subf r29,r5,r17
  REX_STORE_U32(arena + kArenaTop, uint32_t(scratch));                 // stw r29,32(r7)

  const uint64_t tail_offset = REX_LOAD_U16(voice + kTailOffset);      // lhz r9,76(r31)
  const uint64_t bias = REX_LOAD_U8(voice + kTailBias);                // lbz r4,81(r31)
  const uint64_t usable = available - bias;                            // subf r3,r4,r22
  const uint32_t src_desc = REX_LOAD_U32(stream + kPairBack);          // lwz r27,28(r19)
  const uint64_t needed = usable + 1;                                  // addic. r11,r3,1
  const uint32_t dst_desc = REX_LOAD_U32(stream + kPairFront);         // lwz r26,32(r19)
  const uint64_t tail_base = tail_offset + uint64_t(voice);            // add r18,r9,r31

  // How many output frames this block can produce. The test is `addic.`'s cr0 on the LOW word.
  uint32_t frames = 0;                                    // mr r25,r20 -- r20 is zero throughout
  if (int32_t(uint32_t(needed)) > 0) {                    // bgt 0x82b2dc40
    const uint32_t step = REX_LOAD_U32(voice + kStep);    // lwz r9,68(r31)
    if (step == 0) {                                      // cmplwi ; bne
      frames = uint32_t(kStepFreeFrames);                 // li r25,8192
    } else {
      const uint64_t phase = REX_LOAD_U32(voice + kPhase);                       // lwz r8,72(r31)
      const uint64_t scaled = uint64_t(uint32_t(needed) << 16) & 0xFFFF0000ull;  // rlwinm r7,r11,16,0,15
      // twllei r9,0 -- provably dead: this arm is only reached when the step is non-zero.
      const uint64_t span = scaled - phase;               // subf r11,r8,r7
      const uint64_t last = span - 1;                     // addi r6,r11,-1
      frames = uint32_t(last) / step;                     // divwu r25,r6,r9
    }
  }
  // loc_82B2DC6C -- clamped by the block cap, on both arms.
  const uint32_t cap = REX_LOAD_U16(voice + kFrameCap);   // lhz r11,78(r31)
  if (frames > cap) frames = cap;                         // cmplw ; ble ; mr r25,r11

  // loc_82B2DC7C
  uint32_t channels = REX_LOAD_U8(voice + kChannels);     // lbz r9,42(r31)
  uint32_t phase_word = 0;                                // mr r11,r20
  uint64_t leftover = 0;                                  // mr r30,r20
  if (channels != 0) {                                    // beq cr6,0x82b2ddc8
    const uint64_t run_bytes = Scale4(input_frames);      // rlwinm r23,r10,2,0,29
    uint64_t tail_index = 0;                              // mr r21,r20
    uint64_t tail_row = tail_base;                        // mr r24,r18
    uint32_t channel = 0;                                 // mr r28,r20
    do {                                                  // loc_82B2DCA0
      // Reloaded every iteration, and only written after the loop, so it is constant here.
      const uint64_t carried = REX_LOAD_U8(voice + kTailCount);  // lbz r30,80(r31)
      if (carried != 0) {                                        // cmplwi ; beq
        // bl 0x82f52fb8 -- memcpy(scratch, tail_row, 4*carried): the previous block's tail leads
        // the scratch run. rotlwi r5,r11,2 on a byte is 4*carried.
        skate3::audio::GuestCall(ctx, base, sub_82F52FB8, scratch, tail_row,
                                 uint64_t(__builtin_rotateleft32(uint32_t(carried) & 0xFF, 2)));
      }
      // loc_82B2DCC0 -- the new input goes in behind it, then the whole run is resampled.
      const uint64_t src_stride = REX_LOAD_U16(src_desc + kChannelStride);  // lhz r11,14(r27)
      const uint64_t carried_bytes = Scale4(carried);                       // rlwinm r9,r30,2,0,29
      const uint64_t dst_stride = REX_LOAD_U16(dst_desc + kChannelStride);  // lhz r7,14(r26)
      const uint64_t src_base = REX_LOAD_U32(src_desc + kBufferBase);       // lwz r11,4(r27)
      const uint64_t dst_base = REX_LOAD_U32(dst_desc + kBufferBase);       // lwz r10,4(r26)
      const uint64_t source = ChannelAddress(src_stride, channel, src_base);    // add r4,r8,r11
      const uint64_t scratch_body = carried_bytes + scratch;                    // add r3,r9,r29
      const uint64_t destination = ChannelAddress(dst_stride, channel, dst_base);  // add r30,r11,r10
      // bl 0x82edf460 -- memcpy(scratch + 4*carried, source channel, 4*input_frames)
      skate3::audio::GuestCall(ctx, base, sub_82EDF460, scratch_body, source, run_bytes);

      const uint64_t phase = REX_LOAD_U32(voice + kPhase);  // lwz r11,72(r31)
      REX_STORE_U32(frame + kIndexSlot, 0);                 // stw r20,80(r1)
      const uint64_t phase_init = uint64_t(uint32_t(phase) << 16) & 0xFFFF0000ull;  // rlwinm r10,r11,16,0,15
      const uint32_t step = REX_LOAD_U32(voice + kStep);    // lwz r8,68(r31)
      REX_STORE_U32(frame + kPhaseSlot, uint32_t(phase_init));  // stw r10,84(r1)
      // bl 0x82b43fb8 -- the verified resampler port: frames singles out of the scratch run into
      // the destination channel, with the cursor and the phase in this frame's two slots.
      skate3::audio::GuestCall(ctx, base, sub_82B43FB8, uint64_t(frames), scratch, destination,
                               uint64_t(frame) + kIndexSlot, uint64_t(frame) + kPhaseSlot,
                               uint64_t(step));

      // What the resampler did not consume becomes this channel's tail row.
      const uint64_t consumed = REX_LOAD_U32(frame + kIndexSlot);  // lwz r10,80(r1)
      uint64_t copied = 0;                                         // mr r11,r20
      leftover = available - consumed;                             // subf r30,r10,r22
      if (int32_t(uint32_t(leftover)) >= 4) {                       // cmpwi cr6,r30,4 ; blt
        const uint64_t biased = leftover - 4;                                  // addi r9,r30,-4
        const uint64_t consumed_bytes = Scale4(consumed);                      // rlwinm r11,r10,2,0,29
        const uint64_t groups = uint64_t((uint32_t(biased) >> 2) & 0x3FFFFFFFu) + 1;  // rlwinm r9,r9,30,2,31 ; addi +1
        uint64_t from = consumed_bytes + scratch - 4;  // add r11,r11,r29 ; addi r8,r11,-4
        uint64_t to = tail_row - 4;                    // addi r7,r24,-4
        copied = Scale4(groups);                       // rlwinm r11,r9,2,0,29
        uint32_t trips = uint32_t(groups);             // mtctr r9
        do {                                           // loc_82B2DD5C
          ctx.fpscr.disableFlushModeUnconditional();
          const double a = LoadSingle(base, uint32_t(from) + 4);   // lfs f13,4(r8)
          const double b = LoadSingle(base, uint32_t(from) + 8);   // lfs f12,8(r8)
          const double c = LoadSingle(base, uint32_t(from) + 12);  // lfs f11,12(r8)
          from += 16;                                              // lfsu f0,16(r8)
          const double d = LoadSingle(base, uint32_t(from));
          StoreSingle(base, uint32_t(to) + 4, a);                  // stfs f13,4(r7)
          StoreSingle(base, uint32_t(to) + 8, b);                  // stfs f12,8(r7)
          StoreSingle(base, uint32_t(to) + 12, c);                 // stfs f11,12(r7)
          to += 16;                                                // stfsu f0,16(r7)
          StoreSingle(base, uint32_t(to), d);
        } while (--trips != 0);                                    // bdnz 0x82b2dd5c
      }
      // loc_82B2DD80 -- whatever the four-at-a-time loop left short, byte-copied.
      if (uint32_t(copied) < uint32_t(leftover)) {  // cmplw cr6,r11,r30 ; bge
        const uint64_t out_index = tail_index + copied;      // add r9,r21,r11
        const uint64_t in_index = copied + consumed;         // add r8,r11,r10
        const uint64_t remaining = leftover - copied;        // subf r7,r11,r30
        skate3::audio::GuestCall(ctx, base, sub_82F52FB8,    // bl 0x82f52fb8
                                 Scale4(out_index) + tail_base, Scale4(in_index) + scratch,
                                 Scale4(remaining));
      }
      // loc_82B2DDAC
      channels = REX_LOAD_U8(voice + kChannels);  // lbz r11,42(r31) -- reloaded every iteration
      channel += 1;                               // addi r28,r28,1
      tail_row += kTailRowBytes;                  // addi r24,r24,24
      tail_index += kTailRowFloats;               // addi r21,r21,6
    } while (channel < channels);                 // cmplw cr6,r28,r11 ; blt cr6
    phase_word = REX_LOAD_U32(frame + kPhaseSlot);  // lwz r11,84(r1)
  }

  // loc_82B2DDC8 -- publish. rlwinm r9,r11,16,16,31 is the phase word's high half, which is where
  // sub_82B43FB8 leaves the fraction, moved back down into the low half.
  const uint32_t phase_out = (phase_word >> 16) & 0xFFFFu;
  REX_STORE_U8(voice + kTailCount, uint8_t(leftover));  // stb r30,80(r31) -- the LOW byte only
  ctx.r3.s64 = 1;                                       // li r3,1
  REX_STORE_U32(voice + kPhase, phase_out);             // stw r9,72(r31)
  const uint32_t format = REX_LOAD_U32(stream + kFormat);     // lwz r8,40(r19)
  const uint32_t back = REX_LOAD_U32(stream + kPairBack);     // lwz r7,28(r19)
  const uint32_t front = REX_LOAD_U32(stream + kPairFront);   // lwz r6,32(r19)
  REX_STORE_U32(stream + kPairFront, back);                   // stw r7,32(r19)
  REX_STORE_U32(stream + kPairBack, front);                   // stw r6,28(r19)
  REX_STORE_U32(stream + kInputFrames, frames);               // stw r25,48(r19)
  ctx.fpscr.disableFlushModeUnconditional();
  StoreSingle(base, stream + kStreamRate,
              LoadSingle(base, format + kFormatRate));   // lfs f0,12(r8) ; stfs f0,52(r19)
  // The arena pointer goes back to the value r17 has held since the top of the call, through the
  // system pointer re-read here rather than the one in r8.
  const uint32_t system_now = REX_LOAD_U32(voice + kSystem);  // lwz r5,8(r31)
  const uint32_t arena_now = REX_LOAD_U32(system_now + 0);    // lwz r4,0(r5)
  REX_STORE_U32(arena_now + kArenaTop, arena_top);            // stw r17,32(r4)

  ctx.r1.u32 = entry_sp;  // addi r1,r1,224
  saved.restore(ctx);     // __restgprlr_17
}

// Two paths, and only the first is enumerable.
//
// The rate-changed path is predicted exactly from entry state -- one fcmpu on two singles, neither
// of them written before the test -- and writes exactly two words: the voice's rate cache at +64 and
// the stream's rate at +52.
//
// The resample path is NOT enumerable and returns false. Everything about it derives from entry
// state except one length: each channel's tail row is written for `available - consumed` singles,
// where `consumed` is the input cursor sub_82B43FB8 leaves in this frame's slot at r1+80. That value
// exists only during the call. It could be predicted -- the resampler's index advance telescopes to
// ((phase + frames*step) >> 16) while no group of eight overflows the 16-bit fraction field, the
// guard sub_82B43FB8's own Windows() already uses for its read span -- but a mispredicted length
// here is a write outside the windows into a live mixer object, so the derivation is left to a
// change that can be measured rather than asserted. See the note.
bool Windows(PPCContext& ctx, uint8_t* base, skate3::audio::PortSpec& spec) {
  const uint32_t voice = ctx.r3.u32;
  const uint32_t stream = ctx.r4.u32;
  if (voice == 0 || stream == 0) return false;  // the original would store through null

  const double rate = LoadSingle(base, stream + kStreamRate);
  const double cached = LoadSingle(base, voice + kRateCache);
  if (rate == cached) return false;  // the resample path: see above

  const uint32_t format = REX_LOAD_U32(stream + kFormat);
  if (format == 0) return false;  // the original would load the rate through null

  spec.write(voice + kRateCache, 4);   // stfs f0,64(r3)
  spec.write(stream + kStreamRate, 4);  // stfs f0,52(r4)
  spec.read(stream + kFormat, 4);
  spec.read(format + kFormatRate, 4);
  return true;
}

}  // namespace port_82B2DBA8
SKATE3_PORT(82B2DBA8, skate3::audio::kPortPending, skate3::audio::kReturnR3)
