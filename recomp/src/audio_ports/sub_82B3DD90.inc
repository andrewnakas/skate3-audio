// sub_82B3DD90  role: build the ring window and the segment array for one block, fill them, then zero the tails   lifted: skate3_recomp.68.cpp:11003 (155 lines)
// STATUS: gate-2 (sub_82B3DF90's store bases are the segment output pointers sub_82B3DC48 produces during the call)
// calls/session: boot 330526  play ?  map ?          thread: RwAudioCore Dac
// note: probe/ports/notes/sub_82B3DD90.md
namespace port_82B3DD90 {

// The stream object (r3). Names shared with sub_82B3DB90, sub_82B3DC48, sub_82B3DEA8 and
// sub_82B3DF90, which take the same object; nothing in docs/rw_audio_structs.h names it.
constexpr uint32_t kObjRing = 0;         // the float ring's byte base
constexpr uint32_t kObjBlock = 16;       // sub_82B3DF90's kBlock: the per-segment cap base
constexpr uint32_t kObjSpanHigh = 20;    // sub_82B3DB90's kSpanHigh, sub_82B3DF90's kEnd
constexpr uint32_t kObjSpanLow = 24;     // sub_82B3DB90's kSpanLow
constexpr uint32_t kObjLimit0 = 40;      // sub_82B3DF90's kLimit0: segment 0's word count
constexpr uint32_t kObjLimit1 = 44;      // sub_82B3DF90's kLimit1: segment 1's word count
constexpr uint32_t kObjPosition = 52;    // the running word position
constexpr uint32_t kObjTwoBuffers = 56;  // u8: non-zero means a second segment

// The 16-byte ring window, on this function's own frame, handed to sub_82B3DC48 as r4 and read
// by sub_82B3DB90.
constexpr uint32_t kWinBase = 0;         // sub_82B3DB90's kRingBase
constexpr uint32_t kWinEnd = 4;          // sub_82B3DB90's kRingEnd
constexpr uint32_t kWinLagged = 8;       // ring end less the lag; stored, read by nobody here
constexpr uint32_t kWinCursor = 12;      // sub_82B3DB90's kCursor

// The segment array, also on this frame, handed to sub_82B3DC48 as r5.
constexpr uint32_t kSegNeed = 0;
constexpr uint32_t kSegCap = 4;
constexpr uint32_t kSegRank = 8;    // written by sub_82B3DC48, not here
constexpr uint32_t kSegOut = 12;    // written by sub_82B3DC48, read back here
constexpr uint32_t kSegStride = 16;

// The caller's output record (r6), at the caller's frame + 80. sub_82B3DEA8 reads +16 back.
constexpr uint32_t kOutSeg0 = 4;
constexpr uint32_t kOutSeg1 = 8;
constexpr uint32_t kOutEnd = 16;

// The frame the original builds, and where the two structures sit in it.
constexpr uint32_t kFrameSize = 176;
constexpr uint32_t kWindowOffset = 80;
constexpr uint32_t kSegmentsOffset = 96;

// rlwinm rN,rX,2,0,29 -- the low word scaled by four, zero-extended back to 64 bits.
inline uint64_t WordsToBytes(uint64_t value) {
  return (uint64_t(uint32_t(value)) << 2) & 0xFFFFFFFCull;
}

REX_FUNC(Native) {
  const uint32_t object = ctx.r3.u32;      // mr r31,r3 -- the low word, for the loads
  const uint64_t object_wide = ctx.r3.u64; // ...and all 64 bits, for mr r3,r31 at both calls
  const uint32_t out = ctx.r6.u32;         // mr r29,r6
  const uint64_t out_wide = ctx.r6.u64;    // ...and all 64 bits, for mr r5,r29
  const uint64_t consumed = ctx.r5.u64;    // mr r30,r5
  const int32_t block_index = ctx.r4.s32;

  // stwu r1,-176(r1). Unlike most ports this one has to build its frame: the ring window and the
  // segment array live in it and their addresses are passed to sub_82B3DC48, so they need real
  // guest memory at the same place. The frame is below the caller's r1, dies with the call, and
  // is what the brief excludes from the windows; r1 is restored before returning.
  const uint32_t frame = ctx.r1.u32 - kFrameSize;
  REX_STORE_U32(frame, ctx.r1.u32);
  ctx.r1.u32 = frame;
  const uint32_t window = frame + kWindowOffset;
  const uint32_t segments = frame + kSegmentsOffset;

  const uint64_t position = REX_LOAD_U32(object + kObjPosition);   // lwz r6,52(r3)
  const uint64_t span = REX_LOAD_U32(object + kObjSpanHigh);       // lwz r3,20(r3)
  const uint64_t reach = position + consumed;                      // add r7,r6,r30, 64-bit
  // mullw r6,r3,r4 -- the full 64-bit product of the sign-extended low words.
  const uint64_t block = uint64_t(int64_t(int32_t(uint32_t(span))) * int64_t(block_index));
  const uint64_t limit0 = REX_LOAD_U32(object + kObjLimit0);       // lwz r4,40(r31)
  const uint64_t ring = REX_LOAD_U32(object + kObjRing);           // lwz r11,0(r31)
  const uint64_t lag = REX_LOAD_U32(object + kObjSpanLow);         // lwz r10,24(r31)
  const uint64_t cap_base = REX_LOAD_U32(object + kObjBlock);      // lwz r9,16(r31)
  const uint32_t two = REX_LOAD_U8(object + kObjTwoBuffers);       // lbz r28,56(r31)
  REX_STORE_U32(segments + kSegNeed, uint32_t(limit0));            // stw r4,96(r1)
  REX_STORE_U32(segments + kSegOut, 0);                            // stw r5,108(r1)
  // divw r4,r7,r3
  const uint64_t quotient = uint32_t(
      (int32_t(uint32_t(span)) &&
       !(int32_t(uint32_t(reach)) == INT32_MIN && int32_t(uint32_t(span)) == -1))
          ? int32_t(uint32_t(reach)) / int32_t(uint32_t(span))
          : 0);
  const uint64_t block_bytes = WordsToBytes(block);                // rlwinm r8,r6,2,0,29
  // mullw r6,r4,r3 -- again 64-bit.
  const uint64_t whole =
      uint64_t(int64_t(int32_t(uint32_t(quotient))) * int64_t(int32_t(uint32_t(span))));
  const uint64_t ring_start = block_bytes + ring;                  // add r11,r8,r11
  const uint64_t remainder = reach - whole;                        // subf r8,r6,r7
  // rotlwi r6,r7,1 ; addi r6,r6,-1
  const uint64_t doubled_less_one =
      uint64_t(int64_t(uint64_t(__builtin_rotateleft32(uint32_t(reach), 1))) - 1);
  REX_STORE_U32(window + kWinBase, uint32_t(ring_start));          // stw r11,80(r1)
  const uint64_t offset = remainder + lag;                         // add r4,r8,r10
  const uint64_t span_bytes = WordsToBytes(span);                  // rlwinm r7,r3,2,0,29
  const uint64_t lag_bytes = WordsToBytes(lag);                    // rlwinm r27,r10,2,0,29
  const uint64_t ring_end = span_bytes + ring_start;               // add r10,r7,r11
  const uint64_t offset_bytes = WordsToBytes(offset);              // rlwinm r8,r4,2,0,29
  const uint64_t guard = span & ~doubled_less_one;                 // andc r4,r3,r6
  REX_STORE_U32(window + kWinEnd, uint32_t(ring_end));             // stw r10,84(r1)
  // twllei r3,0 -- ppc_trap(type 0) only warns and returns, so the body carries on with the
  // divw's zero quotient, exactly as the lifted form does.
  if (int32_t(uint32_t(span)) == 0) ppc_trap(ctx, base, 0);
  const uint64_t cursor = offset_bytes + ring_start;               // add r3,r8,r11
  const uint64_t cap0 = uint64_t(int64_t(cap_base) + 255);         // addi r11,r9,255
  const uint64_t lagged = ring_end - lag_bytes;                    // subf r10,r27,r10
  REX_STORE_U32(window + kWinCursor, uint32_t(cursor));            // stw r3,92(r1)
  uint64_t count = 1;                                              // li r6,1
  REX_STORE_U32(segments + kSegCap, uint32_t(cap0));               // stw r11,100(r1)
  // twlgei r4,-1 -- the divide-overflow guard.
  if (int32_t(uint32_t(guard)) == -1) ppc_trap(ctx, base, 0);
  REX_STORE_U32(window + kWinLagged, uint32_t(lagged));            // stw r10,88(r1)

  // cmplwi cr6,r28,0 ; beq cr6 -- a second segment, with the tighter cap.
  if (two != 0) {
    const uint64_t limit1 = REX_LOAD_U32(object + kObjLimit1);     // lwz r11,44(r31)
    const uint64_t cap1 = uint64_t(int64_t(cap_base) + 127);       // addi r10,r9,127
    count = 2;                                                     // li r6,2
    REX_STORE_U32(segments + kSegStride + kSegOut, 0);             // stw r5,124(r1)
    REX_STORE_U32(segments + kSegStride + kSegCap, uint32_t(cap1)); // stw r10,116(r1)
    REX_STORE_U32(segments + kSegStride + kSegNeed, uint32_t(limit1)); // stw r11,112(r1)
  }

  // bl 0x82b3dc48 -- (object, window, segments, count)
  skate3::audio::GuestCall(ctx, base, sub_82B3DC48, object_wide, uint64_t(window),
                           uint64_t(segments), count);
  const uint64_t seg0_out = REX_LOAD_U32(segments + kSegOut);      // lwz r11,108(r1)
  REX_STORE_U32(out + kOutEnd, ctx.r3.u32);                        // stw r3,16(r29)
  const uint64_t seg1_out = REX_LOAD_U32(segments + kSegStride + kSegOut);  // lwz r10,124(r1)
  REX_STORE_U32(out + kOutSeg0, uint32_t(seg0_out));               // stw r11,4(r29)
  const uint32_t two_again = REX_LOAD_U8(object + kObjTwoBuffers);  // lbz r9,56(r31) -- re-read
  // subfic r8,r9,0 ; subfe r6,r7,r7 ; and r11,r6,r10 -- ~r7 + r7 is all ones whatever r7 holds
  // (r7 is volatile and sub_82B3DC48 clobbered it), so this is just the carry: the second
  // pointer survives only when the flag is set, and otherwise a zero is published. Note that
  // segments + kSegStride + kSegOut was only initialised on the flag's own path, which is why
  // the mask is needed at all.
  const uint64_t mask = 0xFFFFFFFFFFFFFFFFull + (two_again == 0 ? 1ull : 0ull);
  REX_STORE_U32(out + kOutSeg1, uint32_t(mask & seg1_out));        // stw r11,8(r29)

  // bl 0x82b3df90 -- (object, consumed, out): zeroes the tail of each segment.
  skate3::audio::GuestCall(ctx, base, sub_82B3DF90, object_wide, consumed, out_wide);

  ctx.r3.s64 = 256;                 // li r3,256
  ctx.r1.u32 = frame + kFrameSize;  // addi r1,r1,176
}

// Not enumerable from entry state -- gate 2.
//
// The stores of this function itself are three words in the caller's record (+4, +8, +16) plus
// its own frame, and sub_82B3DC48's write set is predictable (see sub_82B3DC48.inc). The wall is
// the last callee: sub_82B3DF90 zero-fills through the pointers at out+4 and out+8, and those
// pointers are the segment output addresses sub_82B3DC48 computes DURING this call, from
// sub_82B3DB90's return values. Its fill LENGTHS then depend on the same values. Nothing about
// the two fill regions exists before the call, so no window can name them; predicting them would
// mean re-deriving sub_82B3DC48's loop and sub_82B3DB90's clamps inside this builder, three
// functions deep, where one slip writes outside the declared windows and reaches the live game.
//
// The body above is still exact and still worth having: it is the reference for the Rust port,
// and once sub_82B3DC48 and sub_82B3DB90 are verified through their own hooks this function is
// covered piecewise by theirs plus sub_82B3DF90's.
bool Windows(PPCContext& ctx, uint8_t* base, skate3::audio::PortSpec& spec) {
  (void)ctx;
  (void)base;
  (void)spec;
  return false;
}

}  // namespace port_82B3DD90
SKATE3_PORT(82B3DD90, skate3::audio::kPortGate2, skate3::audio::kReturnR3)
