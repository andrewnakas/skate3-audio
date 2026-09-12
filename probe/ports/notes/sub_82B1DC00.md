# sub_82B1DC00

- Role: `int f(obj*)` — look up a global doubly-linked list by key, unlink the match, and when that
  leaves the list empty hand the list's companion record to `sub_82B489D0`. Returns 12 in r3 on
  every path, including "list empty" and "no match". 115 lifted lines, one direct callee, no
  imports, no indirect call, no lock, no timebase. Only **6** boot calls, `RwAudioCore Dac`.
- Globals, both computed rather than read by eye: the list holder at `0x83036F4C`
  (`lis -31997` + 28492) with the head at `+8` and the record at `+12`, and
  `0x8307762C` (`lis -31993` + 30252), whose word is loaded into r3 at the top and is
  `sub_82B489D0`'s first argument. `lis`/`addi` leave the holder SIGN-EXTENDED in r8, so the callee
  receives `0xFFFFFFFF83036F58` in r4; reproduced, though it only ever addresses with the low word.
- Arguments: r3 = an object; `u32[r3+8]` is the key. List nodes carry `+0` next, `+4` prev, and are
  embedded 80 bytes into their container, whose `+60` holds the key — `addi r10,r10,-80` then
  `lwz r7,60(r10)`, compared **signed** (`cmpw`).
- Stores (4 B each): `0x83036F54` (the head) when the match is the head; `u32[prev+0]` when the
  node's prev is non-zero; `u32[next+4]` when its next is non-zero. Then, only when the head word
  reads back zero, `sub_82B489D0`'s set.
- The `stwu r1,-96(r1)` **is** reproduced: `sub_82B489D0` spills lr at `r1-8` and allocates 96
  bytes of its own, which must land below this frame. The body's list walk is left **unbounded**,
  exactly as the original; the 4,096-node cap that keeps the window builder finite lives in
  `Windows()`, which refuses the call rather than letting the body disagree about where to stop.
- Predicting the callee from entry state is the one piece of reasoning worth checking. r11 at
  `loc_82B1DCA8` is the head word as re-read after each fixup: if the match was not the head its
  prev is non-null, so the reload sees the untouched (non-zero) word; if it was the head, the word
  holds `u32[node+0]` and every reload returns that. So `sub_82B489D0` runs exactly when the match
  was the head of a one-element list — `node == head && u32[node+0] == 0`, both entry state.
  `Windows()` returns false when any of the three fixups lands on the head word or on the node's
  two link words, since those are all re-read.
- `sub_82B489D0(owner, record)` through `GuestCall`. It writes `u32[record+16]` and
  `u8[record+20] = 3` on every path, plus either `owner+184`, `owner+188`, `u32[record+0]` and
  `u32[u32[record+0]+8]` (the arm where `record == u32[owner+180]`), or nothing further when
  `u8[record+20]` is already 3. Its third arm — `record != u32[owner+180]` and the state is not 3 —
  calls `sub_82B39690`, which unlinks the node from one of two buckets (`bucket+16` / `bucket+20`),
  pushes it on `bucket+12`, and decrements `bucket+24`, re-reading `bucket+12` after stores that
  could alias it. **`Windows()` returns false there: gate 2, on that sub-path only.** The body still
  runs it correctly — it is the same single `GuestCall` — it is simply never compared. `Windows()`
  also returns false when the owner is null, and when any of this function's own three stores landed
  on the three words the callee re-reads (`owner+180`, `record+20`, `record+0`).
- Not gate 1, but worth a second opinion: `sub_82B489D0` marking `u8[record+20] = 3` and
  `sub_82B39690` pushing onto `bucket+12` while decrementing `bucket+24` read as a *release into a
  free pool*. It is pure guest-memory list surgery — no allocator, no host handle, no signal, no
  lock, no indirect call (the census agrees) — so it replays on rewound memory as long as every byte
  is declared, which is exactly why the 82B39690 sub-path is refused instead of guessed at.
- Window budget: at most 8 spans, ~30 bytes. Read set: the two globals, the key, the found node's
  8 bytes, and the first 8 walked containers' key words (the walk's reads truncate silently past
  that; a short read set costs the recorded vector context and nothing else).
- Result mask `kReturnR3`: `li r3,12` is the return value on every path, so it is both observable
  and trivially reproducible.
- Unsure: nothing names either global or the node's container, so "list holder", "record", "owner"
  and "bucket" are descriptive only. At 6 boot calls a session may not reach the compared arm at
  all — check the census counters before reading a clean result as evidence.
- Gate verdict: **gate 2 on the `sub_82B39690` sub-path only**, none elsewhere. STATUS pending:
  written, never compared.
