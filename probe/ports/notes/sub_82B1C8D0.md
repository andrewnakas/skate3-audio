# sub_82B1C8D0

Role: any-nonzero reducer over an inline word array. Returns 1 as soon as one of the first
`count` u32 words is nonzero, 0 if the array is empty or entirely zero.

Arguments: r3 = object pointer. No other register is read.

Layout (undocumented; nothing in `docs/rw_audio_structs.h` matches, so the .inc keeps plain
offsets). The sibling parameter-graph nodes in the same TU use the same shape: a u8 count at
+0 followed by an inline array (`sub_82B1CF50` array at +8, `sub_82B1C878` count at +2).

    +0  u8    count       number of words; zero-extended by `lbz`, so 0..255
    +4  u32[] entries     scanned low to high, scan stops at the first nonzero word

Stores: none. `census.stores_present` is false and the lifted body has no store of any kind;
the only result is r3 (`li r3,1` / `li r3,0`, i.e. all 64 bits set from a sign-extended
immediate).

Exactness notes:
- The count is loaded once into r9 and kept across the loop; it is **not** reloaded per
  iteration the way `sub_82B1C878` reloads its count. The port keeps it in a local.
- The count compare is signed (`cmpwi`/`cmpw`) but `lbz` zero-extends, so `ble cr6` at entry is
  reachable only for count == 0, and the loop-back `blt` compares two small non-negative
  values. Signedness cannot change the result; the port still compares as int32.
- The entry test is `cmpwi cr6,r8,0` on a `lwz` result, i.e. "any bit set", not a signed test.
- r10 is advanced by `addi` on the 64-bit register but only ever consumed as `.u32` by the
  load, so plain uint32_t pointer arithmetic (wrapping at 2^32) is equivalent.

Window rationale: write set is empty, so `Windows()` declares no write spans and returns true
unconditionally. The read span is `object .. object + 4 + 4*count`, bounded at 1024 bytes by
the u8 count. Declaring the full array rather than only the prefix the scan touched is
deliberate: reads are recorded for replay, not diffed.

Gates: 1 pass (leaf, no callees, no imports, no indirect calls, no locks). 2 pass (empty write
set is trivially enumerable). 3 pass (no timebase, no float, purely a function of memory).
4 pass (result is r3, declared as `kReturnR3`). STATUS: pending, awaiting a shadow session.

Unsure: the function has no static call site — it is reached only through a function pointer
(136,270 calls on the boot profile, all on `RwAudioCore Dac`), so the claim that the caller
reads only r3 rests on the body leaving nothing else behind, not on reading a call site. If a
caller turns out to consume a volatile scratch register the mask would need widening, but the
original leaves r8/r9/r10/r11 as loop residue that no sane caller would read.
