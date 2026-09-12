// sub_82B3D4F8  role: mix dispatcher -- unpack a six-pointer buffer descriptor and call the one-gain kernel sub_82B3CF58 when the descriptor's word at +8 is zero, otherwise the two-gain kernel sub_82B3D0A8 with the sixth pointer passed on the stack   lifted: skate3_recomp.68.cpp:9763 (76 lines)
// STATUS: pending
// calls/session: boot 174693  play ?  map ?          thread: RwAudioCore Dac
// note: probe/ports/notes/sub_82B3D4F8.md
namespace port_82B3D4F8 {

// Arguments: r3 = the gain block, r4 = the sample count, r7 = the buffer descriptor.
// r5, r6 and r8-r10 are not read on entry.
//
// The gain block: +16 and +20 are singles. The same object is read at +16..+32 by
// sub_82B39FA0, so this is a gain vector and only its first two slots are used here.
constexpr uint32_t kGain0 = 16;  // lfs f1,16(r6) -- both paths
constexpr uint32_t kGain1 = 20;  // lfs f2,20(r6) -- the two-gain path only
//
// The descriptor: six pointer-sized words plus the selector at +8. Nothing in
// docs/rw_audio_structs.h names it, so the names describe how each word is used.
constexpr uint32_t kDescAddend = 0;    // -> sub_82B3CF58's y (read only)
constexpr uint32_t kDescSource = 4;    // -> sub_82B3CF58's x (read only; its alignment picks
                                       //    the kernel's vector or scalar path)
constexpr uint32_t kDescSelect = 8;    // lwz r8,8(r7) -- zero picks the one-gain kernel
constexpr uint32_t kDescExtra = 12;    // the two-gain path only
constexpr uint32_t kDescMixed = 16;    // -> sub_82B3CF58's z (written: x*gain + y)
constexpr uint32_t kDescCopy = 20;     // -> sub_82B3CF58's w (written: x re-read after z)
constexpr uint32_t kDescBytes = 24;

constexpr uint32_t kFrameBytes = 96;       // stwu r1,-96(r1)
constexpr uint32_t kLinkSlot = 8;          // stw r12,-8(r1), i.e. frame + 88
constexpr uint32_t kStackArgSlot = 84;     // stw r5,84(r1) -- sub_82B3D0A8's lwz r30,84(r1)

// The same overflow guard sub_82B3CF58's port uses on its own window arithmetic. The harness's
// 32 KB budget rejects anything past about 4,000 samples long before this.
constexpr int32_t kMaxEnumerableSamples = 0x01000000;

// lfs: the word reinterpreted as a single, widened to double, exactly as lifted.
inline double LoadSingle(uint8_t* base, uint32_t address) {
  PPCRegister temp{};
  temp.u32 = REX_LOAD_U32(address);
  return static_cast<double>(temp.f32);
}

REX_FUNC(Native) {
  const uint32_t gains = ctx.r3.u32;    // mr r6,r3
  // mr r3,r4 -- the kernels' sample count. r4 itself is never reassigned, so r3 and r4 both
  // hold it at either call; neither kernel reads r4 on entry, and it is passed below only so
  // the register state the callee sees matches the original exactly.
  const uint64_t count = ctx.r4.u64;
  const uint32_t desc = ctx.r7.u32;     // mr r11,r7

  // The frame is reproduced because it carries an outgoing argument: sub_82B3D0A8 reads
  // 84(r1) off it. The link-register slot is at frame + 88 and the back chain at frame + 0;
  // both are inside the frame this call allocates, so neither is a window.
  const uint32_t entry_sp = ctx.r1.u32;
  ctx.r12.u64 = ctx.lr;                                    // mflr r12
  REX_STORE_U32(entry_sp - kLinkSlot, ctx.r12.u32);        // stw r12,-8(r1)
  const uint32_t frame = entry_sp - kFrameBytes;           // stwu r1,-96(r1)
  REX_STORE_U32(frame, entry_sp);
  ctx.r1.u32 = frame;

  const uint32_t select = REX_LOAD_U32(desc + kDescSelect);  // lwz r8,8(r7)
  ctx.fpscr.disableFlushModeUnconditional();
  ctx.f1.f64 = LoadSingle(base, gains + kGain0);             // lfs f1,16(r6)

  // cmplwi cr6,r8,0 ; bne cr6,0x82b3d544
  if (select == 0) {
    const uint32_t copy = REX_LOAD_U32(desc + kDescCopy);      // lwz r8,20(r7)
    const uint32_t mixed = REX_LOAD_U32(desc + kDescMixed);    // lwz r7,16(r7)
    const uint32_t source = REX_LOAD_U32(desc + kDescSource);  // lwz r6,4(r11)
    const uint32_t addend = REX_LOAD_U32(desc + kDescAddend);  // lwz r5,0(r11)
    // bl 0x82b3cf58 -- z = x*f1 + y and w = x, n samples. Through GuestCall on the live
    // context so the callee's own hook decides how it runs.
    skate3::audio::GuestCall(ctx, base, sub_82B3CF58, count, count, addend, source, mixed, copy);
  } else {
    // loc_82B3D544
    const uint32_t copy = REX_LOAD_U32(desc + kDescCopy);      // lwz r5,20(r11)
    ctx.fpscr.disableFlushModeUnconditional();
    ctx.f2.f64 = LoadSingle(base, gains + kGain1);             // lfs f2,20(r6)
    const uint32_t mixed = REX_LOAD_U32(desc + kDescMixed);    // lwz r10,16(r11)
    const uint32_t extra = REX_LOAD_U32(desc + kDescExtra);    // lwz r9,12(r11)
    const uint32_t source = REX_LOAD_U32(desc + kDescSource);  // lwz r7,4(r11)
    const uint32_t addend = REX_LOAD_U32(desc + kDescAddend);  // lwz r6,0(r11)
    // stw r5,84(r1) -- the sixth pointer as an outgoing stack argument. Inside this call's own
    // frame, so it is not a window; the value is the same one the original stores.
    REX_STORE_U32(ctx.r1.u32 + kStackArgSlot, copy);
    // bl 0x82b3d0a8 -- eight register arguments: the selector word stays live in r8 and the
    // sixth pointer is passed in r5 as well as on the stack, exactly as lifted.
    skate3::audio::GuestCall(ctx, base, sub_82B3D0A8, count, count, copy, addend, source,
                             static_cast<uint64_t>(select), extra, mixed);
  }

  ctx.r1.s64 = ctx.r1.s64 + kFrameBytes;                         // addi r1,r1,96
  ctx.r12.u64 = REX_LOAD_U32(ctx.r1.u32 - kLinkSlot);            // lwz r12,-8(r1)
  ctx.lr = ctx.r12.u64;                                          // mtlr r12
}

// Every byte the call writes, from ENTRY state only. The selector at +8 picks the path and is
// readable before the call, so the refusal below is predicted, not discovered.
bool Windows(PPCContext& ctx, uint8_t* base, skate3::audio::PortSpec& spec) {
  const uint32_t desc = ctx.r7.u32;
  spec.read(desc, kDescBytes);
  spec.read(ctx.r3.u32 + kGain0, 8);

  // The two-gain path reaches sub_82B3D0A8: 662 lines, eight stvx128 and nine stfsx into six
  // buffers whose cursors and inter-buffer deltas are built inside its loops (18 gate-2
  // suspects in the census). Its write set is not enumerable from here, and over-declaring a
  // guessed superset is not acceptable: a byte it writes outside the windows would be replayed
  // twice against the live game. Refuse until sub_82B3D0A8's own port lands a Windows() to
  // mirror, the way the one-gain path below mirrors sub_82B3CF58's.
  if (REX_LOAD_U32(desc + kDescSelect) != 0) return false;

  // The one-gain path: sub_82B3CF58 writes z and w, four bytes per sample each. Its vector body
  // runs only when the source is 16-byte aligned, and its stvx128 address masking rounds each
  // written run DOWN, so the vector spans start at the 16-byte floor of the base. This is the
  // same enumeration its own port declares, with the arguments unpacked from the descriptor.
  const int32_t count = ctx.r4.s32;  // the callee's r3
  if (count <= 0) return true;       // the kernel's `bge` leaves before any store outside its frame
  if (count > kMaxEnumerableSamples) return false;

  const uint32_t addend = REX_LOAD_U32(desc + kDescAddend);
  const uint32_t source = REX_LOAD_U32(desc + kDescSource);
  const uint32_t mixed = REX_LOAD_U32(desc + kDescMixed);
  const uint32_t copy = REX_LOAD_U32(desc + kDescCopy);

  const uint32_t blocks = ((source & 0xFu) == 0) ? static_cast<uint32_t>(count / 16) : 0;
  if (blocks != 0) {
    const uint32_t bytes = blocks * 64;
    spec.write(mixed & ~0xFu, bytes);
    spec.write(copy & ~0xFu, bytes);
    spec.read(source & ~0xFu, bytes);
    spec.read(addend & ~0xFu, bytes);
  }
  const uint32_t done = blocks * 16;
  if (done < static_cast<uint32_t>(count)) {
    const uint32_t offset = done * 4;
    const uint32_t bytes = (static_cast<uint32_t>(count) - done) * 4;
    spec.write(mixed + offset, bytes);
    spec.write(copy + offset, bytes);
    spec.read(source + offset, bytes);
    spec.read(addend + offset, bytes);
  }
  return true;
}

}  // namespace port_82B3D4F8
SKATE3_PORT(82B3D4F8, skate3::audio::kPortPending, skate3::audio::kReturnNone)
