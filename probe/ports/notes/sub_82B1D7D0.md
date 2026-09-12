# sub_82B1D7D0

Leaf, 13 lines, one store. Take-and-clear of a byte flag: r3 = u8[r3+25] (zero-extended to
64 bits), then u8[r3+25] = 0. Argument: r3 = object pointer. Thread: RwAudioCore Dac,
314,940 calls per boot session -- a per-tick poll of some "pending" flag.

Store: `r3 + 25`, 1 byte. Window `{r3+25, 1}`, from entry state; the read is the same byte and
is covered by the window (the harness snapshots windows before the call).

Gates: 1 pass (no callees, no imports, no locks); 2 pass (one fixed-offset byte); 3 pass (no
timebase); 4 satisfied -- the store is windowed and the return is `kReturnR3`. r10/r11 are
volatile scratch and not compared; the body does not reproduce them.

Unsure: the caller is not visible statically -- `0x82B1D7D0` appears only in the function
table (`skate3_init.cpp`, `skate3_register.cpp`), so it is dispatched through a method table.
Whether any caller reads r3 is therefore unknown, but r3 is fully determined by entry state
and reproduced exactly, so comparing it cannot produce a false divergence. `rw_audio_structs.h`
names +0x19 as `rw_xma_stream.buffer_sel`; there is no evidence this function takes an
`rw_xma_stream` (a 0x1C-stride feeder record), so the offset is left as a plain constant.
