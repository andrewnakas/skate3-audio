#include "rw_audio_structs.h"
#include <stddef.h>
#define CHECK(t,f,o) _Static_assert(offsetof(t,f)==(o), #t "." #f " should be at " #o)
CHECK(rw_system, list_14,          0x14);
CHECK(rw_system, list_1c,          0x1C);
CHECK(rw_system, list_20,          0x20);
CHECK(rw_system, cmd_buffer,       0x30);
CHECK(rw_system, lock_fn,          0x54);
CHECK(rw_system, unlock_fn,        0x58);
CHECK(rw_system, critical_section, 0x60);
CHECK(rw_system, scheduler,        0x70);
CHECK(rw_system, cmd_write_off,    0xCC);
CHECK(rw_system, cmd_high_water,   0xD0);
CHECK(rw_system, time_commands,    0xE8);
CHECK(rw_system, time_phases,      0xF4);
CHECK(rw_system, drain_count,      0x100);
CHECK(rw_scheduler, buckets,       0x10);
CHECK(rw_scheduler, delta_time,    0x40);
CHECK(rw_scheduler, current_node,  0x44);
CHECK(rw_scheduler, node_removed,  0x4C);
CHECK(rw_player, system,           0x08);
CHECK(rw_player, source,           0x50);
CHECK(rw_player, packet_head,      0x148);
CHECK(rw_player, packet_tail,      0x14C);
CHECK(rw_player, decoder,          0x150);
CHECK(rw_player, sample_rate,      0x154);
CHECK(rw_player, state,            0x15E);
CHECK(rw_player, channel_count,    0x15F);
CHECK(rw_player, format_index,     0x160);
CHECK(rw_player, stop_field172,     0x172);
CHECK(rw_player, stop_field173,     0x173);
CHECK(rw_player, stop_field174,     0x174);
CHECK(rw_packet, next,             0x0C);
CHECK(rw_xma_stream, source,     0x04);
CHECK(rw_xma_stream, remaining,  0x08);
CHECK(rw_xma_stream, start_bits, 0x14);
CHECK(rw_xma_stream, out_cursor, 0x0C);
CHECK(rw_xma_stream, sample_credit, 0x10);
CHECK(rw_xma_stream, channels,   0x18);
CHECK(rw_xma_stream, buffer_sel, 0x19);
_Static_assert(sizeof(rw_xma_stream)==0x1C, "rw_xma_stream stride must be 0x1C");
int main(void){return 0;}
