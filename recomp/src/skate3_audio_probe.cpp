/**
 * @file        skate3_audio_probe.cpp
 * @brief       Read-only probe of the XMA input feed, for format research
 *
 * Static reading of the decompiled audio code left one question open: what
 * exactly is handed to the hardware XMA decoder. `sub_82B4FE40` feeds each
 * context in 0x800-byte chunks through `sub_82B4FD40`, which decompiles to a
 * plain VMX128 memcpy - so whatever the source buffer holds is byte-for-byte
 * what the decoder sees. Three separate attempts to find the code that binds
 * source buffers to streams failed, because the struct offsets involved
 * (+0x24, +0x34, +0x3c, +0x44) are too common to grep for.
 *
 * Rather than keep reading, observe it. This hook logs the source address and
 * length of each feed plus the first bytes at that address, which settles two
 * things at once:
 *
 *   - whether the bytes are conventional XMA2 packets (a valid packet header
 *     has metadata == 1 in the low 3 bits of byte 2), and
 *   - whether the lengths and source strides look like file offsets or like
 *     sample-space quantities, which is the open question in
 *     docs/xma-transcode.md.
 *
 * The hook changes no behaviour: it records arguments and calls the original.
 * It is off by default and bounded, because this path runs at audio rate.
 *
 * A second hook, on `sub_828E2B48`, logs the messages game code posts to audio
 * objects: which object (by its entry in the 72-entry name table at 0x8302D4A4,
 * whose handle slots start at 0x8302EE28) and the payload words. That turns
 * "which game event reaches which bank, with what arguments" into a trace
 * (docs/audio-banks.md, "How the game addresses a player sound object").
 */

#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include <rex/cvar.h>
#include <rex/logging.h>

#include "generated/skate3_init.h"

REXCVAR_DEFINE_BOOL(skate3_audio_probe_feed, false, "Skate 3",
                    "Log the first few XMA input feeds (source, length, leading bytes).\n"
                    "\n"
                    "Research aid for the audio format work; harmless but noisy. The feed "
                    "runs at audio rate, so output is capped by "
                    "skate3_audio_probe_feed_count.");

REXCVAR_DEFINE_UINT32(skate3_audio_probe_feed_count, 24, "Skate 3",
                      "How many XMA input feeds to log before going quiet.");

namespace {

std::atomic<uint64_t> g_feeds{0};

}  // namespace

// sub_82B4FD40(dst, src, len) - the VMX128 memcpy that fills an XMA input
// buffer. r3 = destination (the context's input buffer), r4 = source, r5 = length.
extern "C" REX_FUNC(sub_82B4FD40) {
  const uint32_t dst = ctx.r3.u32;
  const uint32_t src = ctx.r4.u32;
  const uint32_t len = ctx.r5.u32;

  __imp__sub_82B4FD40(ctx, base);

  // Read the cvars exactly once. This is a general-purpose fast memcpy inside the
  // audio module, called at audio rate and possibly with a lock held; a cvar
  // lookup per call is both wasteful and a plausible way to deadlock against
  // whatever the cvar store uses internally. The counter is checked first so the
  // steady state after the cap is a single relaxed atomic load.
  static const bool enabled = REXCVAR_GET(skate3_audio_probe_feed);
  static const uint64_t cap = REXCVAR_GET(skate3_audio_probe_feed_count);
  if (!enabled || g_feeds.load(std::memory_order_relaxed) >= cap || src == 0) {
    return;
  }
  const uint64_t n = g_feeds.fetch_add(1, std::memory_order_relaxed);
  if (n >= cap) {
    return;
  }

  // First four words at the source, and the XMA2 packet fields they would mean
  // if this were conventional packet framing.
  const uint32_t w0 = REX_LOAD_U32(src);
  const uint32_t w1 = REX_LOAD_U32(src + 4);
  const uint32_t w2 = REX_LOAD_U32(src + 8);
  const uint32_t w3 = REX_LOAD_U32(src + 12);
  const uint8_t b0 = static_cast<uint8_t>(w0 >> 24);
  const uint8_t b1 = static_cast<uint8_t>(w0 >> 16);
  const uint8_t b2 = static_cast<uint8_t>(w0 >> 8);
  const uint8_t b3 = static_cast<uint8_t>(w0);
  const uint32_t frame_count = b0 >> 2;
  const uint32_t frame_offset_bits = ((b0 & 3u) << 13) | (b1 << 5) | (b2 >> 3);
  const uint32_t metadata = b2 & 7u;

  REXLOG_INFO(
      "skate3-audio-probe: feed {} dst={:08X} src={:08X} len={} ({:#x}) | "
      "[{:08X} {:08X} {:08X} {:08X}] | as-XMA2 frames={} offset_bits={} "
      "metadata={} skip={} -> {}",
      n, dst, src, len, len, w0, w1, w2, w3, frame_count, frame_offset_bits, metadata, b3,
      metadata == 1 ? "PLAUSIBLE packet" : "not a packet header");
}

REXCVAR_DEFINE_BOOL(skate3_audio_probe_messages, false, "Skate 3",
                    "Log messages posted to audio objects (object name and payload words).\n"
                    "\n"
                    "Research aid for the player-sound work. Full lines are capped by "
                    "skate3_audio_probe_messages_count; after that, per-object totals are "
                    "logged every 5000 posts.");

REXCVAR_DEFINE_UINT32(skate3_audio_probe_messages_count, 4000, "Skate 3",
                      "How many audio object messages to log in full.");

namespace {

constexpr uint32_t kObjectTable = 0x8302D4A4;  // {char* name; u16 project; u16 name_id}
constexpr uint32_t kSlotBase = 0x8302EE28;     // entry i's handle slot is kSlotBase + 8*i
constexpr uint32_t kObjects = 72;
constexpr uint32_t kPayloadWords = 28;         // the largest player message ends at +0x74

std::atomic<uint64_t> g_messages{0};
std::array<std::atomic<uint64_t>, kObjects + 1> g_per_object{};  // last bucket: not a table slot

const char* ObjectName(uint8_t* base, uint32_t index) {
  if (index >= kObjects) {
    return "(other)";
  }
  const uint32_t name = REX_LOAD_U32(kObjectTable + 8 * index);
  return name ? reinterpret_cast<const char*>(base + name) : "(null)";
}

}  // namespace

// sub_828E2B48(slot, payload, message) - post a message to an audio object's listeners.
// r3 = handle slot, r4 = payload (message + 4), r5 = message. Returns 0, or -6 / -3 for an
// empty or stale slot, after which the sender resolves the name and posts again.
extern "C" REX_FUNC(sub_828E2B48) {
  static const bool enabled = REXCVAR_GET(skate3_audio_probe_messages);
  if (!enabled) {
    __imp__sub_828E2B48(ctx, base);
    return;
  }
  static const uint64_t cap = REXCVAR_GET(skate3_audio_probe_messages_count);
  const uint32_t slot = ctx.r3.u32;
  const uint32_t payload = ctx.r4.u32;
  uint32_t index = kObjects;
  if (slot >= kSlotBase && slot < kSlotBase + 8 * kObjects && (slot - kSlotBase) % 8 == 0) {
    index = (slot - kSlotBase) / 8;
  }
  g_per_object[index].fetch_add(1, std::memory_order_relaxed);
  const uint64_t n = g_messages.fetch_add(1, std::memory_order_relaxed);

  // Read the payload before the listeners run, in case one consumes it.
  char words[kPayloadWords * 9 + 1] = {0};
  if (n < cap && payload != 0) {
    for (uint32_t i = 0; i < kPayloadWords; ++i) {
      std::snprintf(words + i * 9, 10, "%08X ", REX_LOAD_U32(payload + 4 * i));
    }
  }

  __imp__sub_828E2B48(ctx, base);

  if (n < cap) {
    REXLOG_INFO("skate3-audio-msg: {} obj={} {} slot={:08X} payload={:08X} result={} [{}]", n,
                index, ObjectName(base, index), slot, payload, ctx.r3.s32, words);
  } else if (n % 5000 == 0) {
    std::string totals;
    for (uint32_t i = 0; i <= kObjects; ++i) {
      const uint64_t c = g_per_object[i].load(std::memory_order_relaxed);
      if (c != 0) {
        totals += ObjectName(base, i);
        totals += '=';
        totals += std::to_string(c);
        totals += ' ';
      }
    }
    REXLOG_INFO("skate3-audio-msg: totals after {}: {}", n, totals);
  }
}
