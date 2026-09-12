/* Recovered RenderWare Audio structure layouts — Skate 3, title update 3.
 *
 * Every offset below is read out of the decompiled code and cited to the function it
 * came from. Fields marked (confirmed) independently reproduce a value that
 * skate3recomp-dev/src/skate3_audio_fixes.cpp had inferred from crash dumps; those
 * agree. Fields marked (inferred) are read from a single site and the *meaning* is a
 * reading, not a certainty. Unnamed gaps are genuinely unknown, not padding.
 *
 * Big-endian, 4-byte pointers (Xbox 360, 32-bit addressing).
 */
#ifndef RW_AUDIO_STRUCTS_H
#define RW_AUDIO_STRUCTS_H

#include <stdint.h>

typedef uint32_t rw_ptr; /* guest pointer */

/* ------------------------------------------------------------------ *
 * Command ring record.  sub_82B28A00 (producer), sub_82B48530 (drain)
 *
 * Variable length: the handler returns its own size, and the drain advances by that
 * return value.  Sizes seen: 0x08 (Stop), 0x0C (Submit), 0x14 (Play).
 * ------------------------------------------------------------------ */
typedef struct {
    rw_ptr handler;  /* +0x00 called as handler(record); returns record size */
    rw_ptr object;   /* +0x04 the Player the command applies to            */
    /* payload follows, handler-specific */
} rw_command;

/* Play payload, unpacked by sub_82B28B78.  All three arrive as floats. */
typedef struct {
    rw_ptr  handler;      /* +0x00 */
    rw_ptr  player;       /* +0x04 */
    float   format;       /* +0x08 -> Player.format_index   */
    float   sample_rate;  /* +0x0C -> Player.sample_rate    */
    float   num_channels; /* +0x10 -> Player.channel_count  */
} rw_command_play;

/* ------------------------------------------------------------------ *
 * Scheduler — lives at System + 0x70.  sub_82B48A50
 *
 * The drain ticks bucket 0 and bucket 1 each frame.
 * ------------------------------------------------------------------ */
typedef struct {
    uint8_t _pad00[0x10];
    rw_ptr  buckets[2];      /* +0x10, stride 0x20: head of each node list  */
    uint8_t _pad18[0x28];
    float   delta_time;      /* +0x40 passed to every node's process fn     */
    rw_ptr  current_node;    /* +0x44 set while a node runs, 0 otherwise    */
    uint8_t _pad48[0x04];
    uint32_t node_removed;   /* +0x4C set by a node that removes itself     */
} rw_scheduler;

/* A node in a scheduler bucket. */
typedef struct {
    rw_ptr next;      /* +0x00 */
    rw_ptr _unknown;  /* +0x04 */
    rw_ptr instance;  /* +0x08 the plug-in instance to tick */
} rw_node;

/* A plug-in instance, as the scheduler sees it. */
typedef struct {
    rw_ptr   descriptor;  /* +0x00 ->rw_plugin_desc                          */
    rw_ptr   process;     /* +0x04 called as process(delta_time, context)    */
    rw_ptr   context;     /* +0x08                                           */
    rw_ptr   _unknown0c;  /* +0x0C                                           */
    uint32_t elapsed;     /* +0x10 per-tick time, written when profiling on  */
} rw_instance;

/* ------------------------------------------------------------------ *
 * System.  sub_82B48530, sub_82B28A00, sub_82B47E68
 * ------------------------------------------------------------------ */
typedef struct {
    uint8_t  _pad00[0x14];
    rw_ptr   list_14;         /* +0x14 walked by the drain's fade pass       */
    uint8_t  _pad18[0x04];
    rw_ptr   list_1c;         /* +0x1C walked by sub_82B482F8               */
    rw_ptr   list_20;         /* +0x20 walked by sub_82B48440               */
    uint8_t  _pad24[0x0C];
    rw_ptr   cmd_buffer;      /* +0x30 command ring base       (confirmed)  */
    uint8_t  _pad34[0x20];
    rw_ptr   lock_fn;         /* +0x54 optional; else RtlEnter (confirmed)  */
    rw_ptr   unlock_fn;       /* +0x58 optional; else RtlLeave (confirmed)  */
    uint8_t  _pad5c[0x04];
    rw_ptr   critical_section;/* +0x60 RTL_CRITICAL_SECTION*   (confirmed)  */
    uint8_t  _pad64[0x0C];
    rw_scheduler scheduler;   /* +0x70                                      */
    uint8_t  _padc0[0x0C];
    uint32_t cmd_write_off;   /* +0xCC bytes used; reset each drain (confirmed) */
    uint32_t cmd_high_water;  /* +0xD0 peak ring usage                      */
    uint8_t  _padd4[0x14];
    uint32_t time_commands;   /* +0xE8 command-phase elapsed                */
    uint8_t  _padec[0x08];
    uint32_t time_phases;     /* +0xF4 accumulated earlier phases           */
    uint8_t  _padf8[0x08];
    uint32_t drain_count;     /* +0x100 incremented once per drain          */
} rw_system;

/* The ring is frame-scoped: filled during the frame, fully consumed and reset by the
 * drain.  It is not a circular buffer with independent read and write cursors. */

/* ------------------------------------------------------------------ *
 * Player (PacketPlayer instance).  sub_82B28B78 / C18 / CC0, sub_82B29018
 * ------------------------------------------------------------------ */
typedef struct {
    uint8_t  _pad00[0x08];
    rw_ptr   system;          /* +0x08   rw_system*            (confirmed)  */
    uint8_t  _pad0c[0x3C];
    rw_ptr   _field48;        /* +0x48   touched by EVENT_STOP              */
    uint8_t  _pad4c[0x04];
    rw_ptr   source;          /* +0x50   source object         (confirmed)  */
    uint8_t  _table54[0x14 * 0x0C]; /* +0x54 20 entries, stride 12;
                                     * discriminator byte at entry +0x09
                                     * (sub_82B28A00's non-append path)     */
    uint8_t  _pad[0x148 - 0x54 - 0x14 * 0x0C];
    rw_ptr   packet_head;     /* +0x148  submitted-packet FIFO head         */
    rw_ptr   packet_tail;     /* +0x14C  FIFO tail                          */
    rw_ptr   decoder;         /* +0x150  active decoder; 0 when idle        */
    uint32_t sample_rate;     /* +0x154                        (confirmed)  */
    uint32_t _field158;       /* +0x158  set to 0xFF on teardown            */
    uint8_t  _pad15c[0x02];
    uint8_t  state;           /* +0x15E  1 = playing, 4 = stopped           */
    uint8_t  channel_count;   /* +0x15F                        (confirmed)  */
    uint8_t  format_index;    /* +0x160  indexes the codec tag table
                              *         at 0x8210A310          (confirmed)  */
    uint8_t  _pad161[0x11];
    uint8_t  stop_field172;   /* +0x172  EVENT_STOP writes 16 (0x10) here.
                              *         Meaning unknown; recorded because a
                              *         verified body writes it.            */
    uint8_t  stop_field173;   /* +0x173  EVENT_STOP clears                  */
    uint8_t  stop_field174;   /* +0x174  EVENT_STOP clears                  */
} rw_player;

/* The struct above ran to +0x161 until 2026-09-11.  sub_82B28C18 (EVENT_STOP),
 * read from the lifted form and reproduced natively, writes three bytes past
 * that -- 16 to +0x172 and zero to +0x173/+0x174 -- so the Player is at least
 * 0x175 bytes.  The values are reproduced because the job is to match the
 * original; what they mean is not established. */

/* A submitted packet; linked through the Player's FIFO. */
typedef struct {
    uint8_t _pad00[0x0C];
    rw_ptr  next;             /* +0x0C  sub_82B28CC0 */
} rw_packet;

/* ------------------------------------------------------------------ *
 * XMA stream record.  sub_82B4FC00 (context setup), sub_82B4FE40 (feeder),
 * sub_82B50B80 (driver, which strides the array by 0x1C at +0x185)
 *
 * An XMA context decodes at most a stereo pair, so a multichannel stream owns
 * several of these -- an array at System-side +0x34 with the count at +0x44.
 * The feeder pushes 0x800 bytes at a time, alternating input buffers.
 * ------------------------------------------------------------------ */
typedef struct {
    rw_ptr   context;      /* +0x00 ->{id, in_buf0, in_buf1, out_buf, ...}      */
    rw_ptr   source;       /* +0x04 current read position; advances by 0x800    */
    uint32_t remaining;    /* +0x08 bytes left to feed                          */
    uint32_t out_cursor;   /* +0x0C output write cursor, wraps at 0x1800
                            *       (sub_82B50B80 output drain)                 */
    uint32_t sample_credit;/* +0x10 samples owed to this stream. Accumulated when a
                            *       segment is bound (sub_82B50B80 setup) and
                            *       decremented as the drain consumes. INFERRED to
                            *       be samples rather than bytes, because the drain
                            *       computes byte counts as credit*channels*2.     */
    int32_t  start_bits;   /* +0x14 initial read offset in BITS; 0x20 is added,
                            *       which is one XMA packet header              */
    uint8_t  channels;     /* +0x18 channels this context decodes (1 or 2).
                            *       Confirmed twice: sub_82B4FC00 writes
                            *       ctx.num_channels = this - 1, and
                            *       sub_82B50B80 computes byte counts as
                            *       channels * samples * 2 (16-bit PCM).        */
    uint8_t  buffer_sel;   /* +0x19 which input buffer to fill next (0 or 1)    */
    uint8_t  _pad1a[0x02];  /* to the 0x1C stride the driver uses               */
} rw_xma_stream;

/* ------------------------------------------------------------------ *
 * Codec tag table at 0x8210A310 — exactly two entries, indexed by
 * Player.format_index.  See rw-audio-core.md.
 * ------------------------------------------------------------------ */
#define RW_FORMAT_16BIT_INT_LE     0x50364C30u /* 'P6L0' PCM 16-bit LE            */
#define RW_FORMAT_FLOAT_INT_NATIVE 0x50464E30u /* 'PFN0' PCM float, host native   */

#endif /* RW_AUDIO_STRUCTS_H */
