# sub_82B4F8C8

- Role: the **acquire half of `sub_82B4FAF8`**, over the same three globals. `u32 f(object*)`,
  returns 1 when every pair got a node and 0 when any pop found the pool empty. 315 lifted lines,
  one direct callee (`sub_82F52040`, a memset), no `bctrl`, two kernel imports.
  1,924 calls per boot on `RwAudioCore Dac` -- against `sub_82B4FAF8`'s 1,917, so the two are the
  construct/destruct pair of one object.
- Globals, each `((lis_imm & 0xFFFF) << 16) + offset`, names kept identical to `sub_82B4FAF8`:
  `0x830845F0` holds the critical-section pointer (loaded per use, never cached);
  `0x830BDEE0` `kSpareHead`, the head this function **pushes** every node it takes onto -- so it is
  the live/in-use head and the sibling's name for it is a misnomer;
  `0x830BDEE4` the anchor, `+0` `kAnchorEnd` (far end), `+4` `kAnchorFront` (newest), `+8` count.
  `0x8231BB04` is the vtable this constructor installs at `object+0`.
- Object: `+46` u8 channel count, `+52` the entry array base, `+60`/`+72`/`+76` zeroed words,
  `+68` the pair count `sub_82B4FAF8` re-reads as its loop bound, `+84` a byte cleared, `+85` a byte
  set to 1, and the array itself **inline at `object+95` rounded DOWN to 8**
  (`addi r10,r3,95 ; rlwinm r7,r10,0,0,28`). Entries are 28 bytes: `+0` the object pointer,
  `+24` u8 channels held by that entry. The intrusive list node is 20 bytes into each object
  (`kLinkPrev` +0 toward the front, `kLinkNext` +4 toward the end), the same layout the sibling uses.
- Flow:
  1. `pairs = ((u8[+46]) + 1) >> 1` (`rlwinm ...,31,1,31` is an unsigned shift right by one).
     Store the vtable, the array base, three zero words, the zero byte, then **reload** `+52` for
     the memset argument, store the pair count and the 1 at `+85`, and
     `sub_82F52040(array, 0, pairs * 28)`.
  2. Per pair, under the lock: pop `[anchor+0]`; the node one step toward the front becomes the new
     end, and if that is null the front is cleared too, otherwise the new end's `kLinkNext` is
     zeroed; the count is decremented **64-bit with the low word stored**, so a count already at 0
     writes 0xFFFFFFFF. Then push the node onto `kSpareHead` (head read, two stores into the node,
     head **re-read**, old head's `kLinkNext` fixed, head published), release the lock, and outside
     it store `node - 20` into the array entry and tag it `2` channels, or `1` when the remaining
     count is <= 1 -- and in that last case the channel counter is **not** decremented.
  3. An empty pop sets a failure flag, releases the lock and **keeps looping**: later passes can
     still succeed, so the array can end up sparsely filled.
  4. No failure -> return 1. Failure -> walk all `pairs` entries, skip the null ones, and under the
     lock (taken and released **per entry**) unlink each node and push it onto the anchor's front,
     bumping the count. Return 0. That walk is `sub_82B4FAF8`'s body with the lock scope narrowed.
- Stores: eight into the object up front (`+0`, `+52`, `+60`, `+68`, `+72`, `+76`, `+84`, `+85`),
  then per pair `anchor+0`, `anchor+4` or a node's `+4`, `anchor+8`, the node's `+0`/`+4`, the old
  head's `+4`, `kSpareHead`, the array entry and its channel byte; on rollback `kSpareHead`, two
  neighbour links, the node's `+0`/`+4`, `anchor+0` or the front's `+0`, `anchor+4`, `anchor+8`.
  Plus the memset's `pairs * 28` bytes.
- Result mask: `kReturnR3`, the literals 1 and 0.
- Gate: **1, fail**, depth 0, reason `import:RtlEnterCriticalSection,RtlLeaveCriticalSection`. It
  takes the global audio lock itself -- once per pair on the success path, twice per filled entry on
  the rollback -- and the pops mutate a global free pool the harness's rewind cannot restore
  (rewinding the object's memory would leave the nodes handed out and the anchor short). Both
  imports are reached through their guest addresses (0x82F9CB44 / 0x82F9CB54) rather than an
  `__imp__` name, because lint check 6 forbids the latter; that writes `ctr`, which the original's
  `bl` does not, and `ctr` is outside the compared set. `Windows()` returns false.
  Gate 2 also fails: the write set spans the global pool and whatever neighbour nodes the chain
  happens to hold. Gate 3 passes (no `mftb`), though the lock makes the result thread-dependent in
  a way gate 3 does not name.
- Unsure:
  - What the pooled objects are. Each is at least 20 bytes before its node, the array element
    allocates 28 bytes but only `+0` and `+24` are written here, and the sibling never reads `+24`.
    A stereo voice pair is the obvious reading and is not evidence.
  - `+84` and `+85`: cleared and set to 1 respectively, and nothing else in this function reads
    them. `+60`, `+72` and `+76` are likewise write-only here.
  - Whether the array inline at `object+95` can ever be unaligned enough for the round-down to move
    it. It moves it whenever the object itself is not 8-aligned at `+95`, i.e. for most alignments,
    so the seven bytes at `+88..+94` are deliberately slack. Not confirmed against an allocation.
  - The re-test `cmplwi cr6,r30,0 ; bne` right after the pop, on a value already known non-zero:
    dead in the original and reproduced as a comment only.
