// sub_82B39FA0  role: mix dispatcher over the same descriptor as sub_82B3D4F8 -- when the word at +8 is zero, call the five-gain kernel sub_82B399D0 with three outgoing stack arguments and latch its returned f1 into the gain block's +32; otherwise just memset the +20 buffer to zero   lifted: skate3_recomp.68.cpp:905 (92 lines)
// STATUS: pending
// calls/session: boot 182370  play ?  map ?          thread: RwAudioCore Dac
// note: probe/ports/notes/sub_82B39FA0.md
namespace port_82B39FA0 {

// Arguments: r3 = the gain block, r4 = the sample count, r5 = an opaque word passed through on
// the stack, r7 = the buffer descriptor. r6 and r8-r10 are not read on entry.
//
// The gain block, read as five singles into f1-f5. +32 is also written: the kernel returns a
// value in f1 and the caller latches it back there, so +32 is running state, not a parameter.
constexpr uint32_t kGain0 = 16;  // lfs f1,16(r31) ; stfs f1,32(r31) latches here
constexpr uint32_t kGain1 = 20;  // lfs f2,20(r31)
constexpr uint32_t kGain2 = 24;  // lfs f3,24(r31)
constexpr uint32_t kGain3 = 28;  // lfs f4,28(r31)
constexpr uint32_t kGainState = 32;  // lfs f5,32(r31) and the store after the call
//
// The descriptor, the same layout sub_82B3D4F8 unpacks. Names describe the use, not a recovered
// struct -- docs/rw_audio_structs.h names none of it.
constexpr uint32_t kDescAddend = 0;   // lwz r9,0(r7)
constexpr uint32_t kDescSource = 4;   // lwz r10,4(r7)
constexpr uint32_t kDescSelect = 8;   // lwz r11,8(r7) -- zero picks the kernel
constexpr uint32_t kDescMixed = 16;   // lwz r8,16(r7) -- also stack argument 84(r1)
constexpr uint32_t kDescCopy = 20;    // lwz r11,20(r7) -- stack argument 92(r1), and the buffer
                                      //   the non-kernel path clears
constexpr uint32_t kDescBytes = 24;

constexpr uint32_t kFrameBytes = 128;  // stwu r1,-128(r1)
constexpr uint32_t kLinkSlot = 8;      // stw r12,-8(r1)
constexpr uint32_t kSaveSlot = 16;     // std r31,-16(r1)
// sub_82B399D0 opens with lwz r11,100(r1) / lwz r26,92(r1) / lwz r8,84(r1) and never does its
// own stwu, so these three slots of this frame are its seventh, eighth and ninth arguments.
constexpr uint32_t kStackArgOpaque = 100;  // stw r5,100(r1)
constexpr uint32_t kStackArgCopy = 92;     // stw r11,92(r1)
constexpr uint32_t kStackArgMixed = 84;    // stw r8,84(r1)

// lfs: the word reinterpreted as a single, widened to double, exactly as lifted.
inline double LoadSingle(uint8_t* base, uint32_t address) {
  PPCRegister temp{};
  temp.u32 = REX_LOAD_U32(address);
  return static_cast<double>(temp.f32);
}

// stfs: round the double back to a single and store its bits.
inline void StoreSingle(uint8_t* base, uint32_t address, double value) {
  PPCRegister temp{};
  temp.f32 = static_cast<float>(value);
  REX_STORE_U32(address, temp.u32);
}

REX_FUNC(Native) {
  const uint32_t gains = ctx.r3.u32;     // mr r31,r3
  const uint64_t count = ctx.r4.u64;     // the kernel's r3 / the clear's element count
  const uint64_t opaque = ctx.r5.u64;    // stored to 100(r1), otherwise untouched
  // r6 is not an argument: sub_82B399D0 overwrites it with a lis constant (line 79 of its
  // lifted body) before any read. Passed through only so the callee's register state matches.
  const uint64_t passthrough_r6 = ctx.r6.u64;
  const uint32_t desc = ctx.r7.u32;

  // The frame is reproduced because it carries three outgoing stack arguments (84/92/100) that
  // sub_82B399D0 reads off it. The link slot at frame + 120 and the r31 slot at frame + 112 are
  // this call's own frame, so they are not windows; the callee's own spills land below frame.
  const uint32_t entry_sp = ctx.r1.u32;
  ctx.r12.u64 = ctx.lr;                                  // mflr r12
  REX_STORE_U32(entry_sp - kLinkSlot, ctx.r12.u32);      // stw r12,-8(r1)
  REX_STORE_U64(entry_sp - kSaveSlot, ctx.r31.u64);      // std r31,-16(r1) -- the entry r31
  const uint32_t frame = entry_sp - kFrameBytes;         // stwu r1,-128(r1)
  REX_STORE_U32(frame, entry_sp);
  ctx.r1.u32 = frame;

  const uint32_t select = REX_LOAD_U32(desc + kDescSelect);  // lwz r11,8(r7)

  // cmplwi cr6,r11,0 ; bne cr6,0x82b3a010
  if (select == 0) {
    const uint32_t copy = REX_LOAD_U32(desc + kDescCopy);      // lwz r11,20(r7)
    const uint32_t mixed = REX_LOAD_U32(desc + kDescMixed);    // lwz r8,16(r7)
    ctx.fpscr.disableFlushModeUnconditional();
    ctx.f5.f64 = LoadSingle(base, gains + kGainState);         // lfs f5,32(r31)
    const uint32_t source = REX_LOAD_U32(desc + kDescSource);  // lwz r10,4(r7)
    ctx.f4.f64 = LoadSingle(base, gains + kGain3);             // lfs f4,28(r31)
    const uint32_t addend = REX_LOAD_U32(desc + kDescAddend);  // lwz r9,0(r7)
    ctx.f3.f64 = LoadSingle(base, gains + kGain2);             // lfs f3,24(r31)
    ctx.f2.f64 = LoadSingle(base, gains + kGain1);             // lfs f2,20(r31)
    REX_STORE_U32(ctx.r1.u32 + kStackArgOpaque, static_cast<uint32_t>(opaque));  // stw r5,100(r1)
    ctx.f1.f64 = LoadSingle(base, gains + kGain0);             // lfs f1,16(r31)
    REX_STORE_U32(ctx.r1.u32 + kStackArgCopy, copy);           // stw r11,92(r1)
    REX_STORE_U32(ctx.r1.u32 + kStackArgMixed, mixed);         // stw r8,84(r1)
    // bl 0x82b399d0 -- r4-r7 keep their entry values (the original never reassigns them on this
    // path), so they are passed through unchanged to match the register state exactly.
    skate3::audio::GuestCall(ctx, base, sub_82B399D0, count, count, opaque, passthrough_r6,
                             static_cast<uint64_t>(desc), mixed, addend, source);
    // stfs f1,32(r31) -- the kernel's result, latched into the gain block.
    ctx.fpscr.disableFlushModeUnconditional();
    StoreSingle(base, gains + kGainState, ctx.f1.f64);
  } else {
    // loc_82B3A010: rlwinm r5,r4,2,0,29 -- four bytes per element, the rotate's wrap masked off.
    const uint64_t length = (static_cast<uint64_t>(ctx.r4.u32) << 2) & 0xFFFFFFFCull;
    const uint32_t target = REX_LOAD_U32(desc + kDescCopy);  // lwz r3,20(r7)
    // li r4,0 ; bl 0x82f52040 -- memset(target, 0, length), through GuestCall like every callee.
    skate3::audio::GuestCall(ctx, base, sub_82F52040, static_cast<uint64_t>(target), 0ull, length);
  }

  // Both paths share this epilogue verbatim.
  ctx.r1.s64 = ctx.r1.s64 + kFrameBytes;                        // addi r1,r1,128
  ctx.r12.u64 = REX_LOAD_U32(ctx.r1.u32 - kLinkSlot);           // lwz r12,-8(r1)
  ctx.lr = ctx.r12.u64;                                         // mtlr r12
  ctx.r31.u64 = REX_LOAD_U64(ctx.r1.u32 - kSaveSlot);           // ld r31,-16(r1)
}

// Every byte the call writes, from ENTRY state only. The selector at +8 picks the path and is
// readable before the call, so the refusal below is predicted, not discovered.
bool Windows(PPCContext& ctx, uint8_t* base, skate3::audio::PortSpec& spec) {
  const uint32_t desc = ctx.r7.u32;
  spec.read(desc, kDescBytes);

  // The kernel path reaches sub_82B399D0: 901 lines, sixteen stvx128 / fourteen stfsx / thirty
  // stfs, with bases that are loop cursors and inter-buffer deltas built inside the call -- 56
  // gate-2 suspects in its census. (One store is easy, into the lis-based global at
  // 0x830D1524; the rest are not.) Not enumerable from here. A guessed superset is not acceptable: the harness replays the
  // callee on rewound memory, so a byte written outside the windows is applied twice to the live
  // game with no rewind. Mirror sub_82B399D0's own Windows() once it has one -- the way
  // sub_82B3D4F8's port mirrors sub_82B3CF58's -- and this path opens up together with the
  // stfs f1,32(r31) latch, which is the only store of this function's own.
  if (REX_LOAD_U32(desc + kDescSelect) == 0) return false;

  // The clear path: memset writes exactly its length, no overshoot (byte-align prologue, then
  // 16-byte blocks, then (len>>2)&3 words, then len&3 bytes -- 16*(n>>4) + 4*((n>>2)&3) + (n&3)
  // == n). Over 32 KB the harness's own budget check takes over and runs the original.
  const uint32_t target = REX_LOAD_U32(desc + kDescCopy);
  const uint32_t length = (ctx.r4.u32 << 2) & 0xFFFFFFFCu;
  if (static_cast<uint64_t>(target) + length > 0xFFFFFFFFull) return false;  // wraps the map
  spec.write(target, length);
  return true;
}

}  // namespace port_82B39FA0
SKATE3_PORT(82B39FA0, skate3::audio::kPortPending, skate3::audio::kReturnNone)
