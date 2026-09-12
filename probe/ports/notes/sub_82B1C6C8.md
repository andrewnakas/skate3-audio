# sub_82B1C6C8

- Role: `u32 f(cursor*)` — step a cursor. Advances the global software clock, takes its running
  total mod 100, then walks a table of **signed** per-step weights accumulating them until the
  running sum exceeds that remainder (unsigned compare, low word only), and publishes
  `base_index + index` into the record's result word. Returns the result word, reloaded from memory
  on every path. 96 lifted lines, one direct callee, closure of 1, no imports, no indirect call, no
  lock, no timebase. 2,420 boot calls on `RwAudioCore Dac`.
- Arguments: r3 = the record. `+0` the source holding the weight table (the weights start at
  `source+16`), `+4` a base index added to the chosen step, `+8` int32 table length (the loop bound,
  **reloaded every iteration**), `+12` the result word — the only store and the return value,
  `+16` int32 enable; zero returns `+12` untouched without even making the call.
- Flow: `u8` weights at `source+16+i` are sign-extended (`extsb`) and summed in 64 bits; the test
  is `cmplw` — **unsigned, on the low 32 bits only**. So a negative weight makes the sum's low word
  huge and trips the test immediately, which is how a `-1` sentinel would terminate the walk; that
  reading is an observation from the instruction forms, not something checked against data. The
  remainder is `now - (now/100)*100` with `now/100` done by the usual reciprocal
  (`0x51EB851F = ((20971 & 0xFFFF) << 16) + 0x851F`, computed) and `rlwinm ...,27,5,31` for the
  `>> 5`. The `subf` is 64-bit on the FULL counter value, so the port keeps it 64-bit even though
  the compare only looks at the low word.
- Stores: `u32[record+12]`, 4 bytes, on one path only — plus `sub_82B1F360`'s 24 bytes at the fixed
  global `0x830775F0`. The `stwu r1,-112(r1)` is **not** reproduced: `sub_82B1F360` is a pure leaf
  that touches no stack at all (checked: its lifted body never names r1), so nothing of its own
  lands below this function's r1, unlike `sub_82B43CC0`'s or `sub_82B49438`'s callees.
- `sub_82B1F360` through `GuestCall`. It is itself a verified port and takes no arguments: it
  advances a six-word cascading counter at `0x830775F0` and returns the full 64-bit running total in
  r3. **Declaring that global as a write window is what makes this function comparable at all** —
  the callee mutates it, so without the rewind the native run would read an already-advanced
  counter and the remainder, the chosen index and the stored result would all differ. The port
  defines the address itself rather than reaching into `port_82B1F360`, so it does not depend on the
  aggregator's include order.
- Window rationale: at most three spans, 28 bytes. The enable word is read before anything else, so
  the do-nothing path is predicted rather than unioned. The conditional store at `+12` is declared
  unconditionally — a superset, and a word the call leaves alone compares equal anyway — which also
  means the loop's break index and the reloaded bound only affect *values*, never addresses. Returns
  false when the record is null and when the record overlaps the clock global (every field but the
  enable word is reloaded after the call, so that overlap is the one thing that would put an address
  outside entry state).
- Unsure: what the record is a cursor over; nothing names it, and the `/100` says the clock's unit is
  probably centi-something but the unit itself was not established. A null `u32[record+0]` with a
  positive count is reproduced, not guarded — the original then reads weights at guest address 16,
  which is a read of the image, not a fault, and it cannot move the write set. The declared read span
  for the weight table is capped at 4096 bytes; that only truncates the recorded vector's context,
  never the compared write set.
- Gate verdict: none fire — the callee is replayable once its global is rewound, the write set is
  enumerable from entry, no timebase, r3 observable. STATUS pending: written, never compared.
