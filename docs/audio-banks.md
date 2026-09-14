# The audio banks — `.abk`, `.csi`, `.ems`, `.bnk`

`audiofiles.big` holds **428 members: 376 `.abk`, 20 `.bnk`, 9 `.csi` and 23 `.ems`**. None
was decoded before this pass. The question they were opened to answer is narrow:

> How does a game event become a sound?

**There is an event-to-sound mapping and it is in these files.** The short answer is that
Skate 3 names every audio object with a string, hashes it, and the hash is the join key
between the game's code, the world data, and the banks. This document says which parts of
that are **demonstrated** — a check the data could have failed, run over the whole
distribution — and which are **corroborated**, meaning the best current reading of bytes
that nothing has yet contradicted.

Everything is reproducible with `cargo run --release --example verify_banks` in
`rust/skate-audio-formats`, which walks the six retail archives and prints agreement
counts. It reported **1,620 checks, all agreeing** when this was written.

---

## The chain, in one picture

```
   a map's .ems               an .abk bank                a .csi project
 ┌──────────────────┐      ┌────────────────────┐      ┌──────────────────┐
 │ position, extent │      │ S10A sample bank   │      │ symbol table     │
 │ gains, flags     │      │ patch table        │      │  name_id -> name │
 │ sound: u64 ──────┼─────▶│ export table       │─────▶│                  │
 └──────────────────┘ hash │  (project, name_id)│  by  └──────────────────┘
                      of a │   -> "c_emitter"   │ pair
                 bank name │   -> "*_msg" in    │
                           │   -> "*_snd" out   │
                           │   -> "*_vol" param │
                           └────────────────────┘
                                     ▲
                                     │ the same object names appear verbatim
                                     │ in the shipping executable's data
                              game code
```

## The join key: two hashes, both read out of the shipping code

### `member_hash` — djb2

The EB entry table's fourth column is **djb2** (`h = h * 33 + c`, seed 5381), byte-exact on
the name as spelled.

**DEMONSTRATED.** 106 of 106 members across `grains.big` (14), `ambience.big` (25),
`ambienceresident.big` (24), `post.big` (39) and `wheels.big` (4). Positionally, not merely
as a set — the *n*-th name hashes to the *n*-th entry's key.

**The exception matters.** `audiofiles.big` matches **0 of 428**. Its column holds small
ascending values (`0x0118A6CA`, `0x02535A35`, …) that are not this hash of the member name,
and what they are is **not established**. `verify_banks` prints that rather than skipping it.

### `name_id` — Bob Jenkins' `lookup8`, seeded `0xABCDEF00_11223344`

The engine-wide 64-bit "hashed id". It was lifted instruction by instruction from
**`sub_82B73AC0`** (`generated/skate3_recomp.70.cpp:17945`): the function loads
`a = b = 0xABCDEF0011223344` and `c = 0x9E3779B97F4A7C13` (the golden-ratio constant), eats
24 bytes at a time little-endian, and runs Jenkins' twelve-step `mix64` — the shift amounts
`43, 9, 8, 38, 23, 5, 35, 49, 11, 12, 18, 22` are visible one for one in the `rldicl`/`rldicr`
masks. The tail reserves the low byte of `c` for the length, exactly as `lookup8` does.

**DEMONSTRATED**, three independent ways:

| check | result |
|---|---|
| `.ems` sound ids vs `hash64` of `audiofiles.big` member names | **48 of 146** distinct ids resolve, covering 254 of 1,796 records |
| the same ids with the two 32-bit halves swapped (negative control) | **0** resolve |
| `lis`/`ori`/`rldimi`-assembled 64-bit constants in the lifted corpus vs strings in the decrypted guest image | **157 of 2,500** resolve — `default`, `challenges`, `StateGraph`, `livingworld_entities`, `SetManualAndWalkAsConnector`, … |

The resolved emitter names are what an ambience designer would write: `trees_rustle`,
`transformer_small_1`, `hvac_system_3`, `clothes_flap`, `water_fountain`, `restaurant_amb`,
`cicadas`, `elevator_loop`, `bird_calls_european`. Each is a real `.abk` in the same archive.

Two of them — `0x643C102A068A31C7` and `0x4A378C3457EE827E`, both in
`speakers_university.ems` — are **also assembled as constants by the shipping code**, in
`sub_8255CAA8` and `sub_8255CB68` (`generated/skate3_recomp.16.cpp:40930`), which compare an
object's `u64` at `+24` against them and on a match substitute
`sub_82B73AC0("contest_intro", 13)`. That is the same 64-bit value appearing in world data
and in code, which is as direct a link between the two as this format offers.

> The trap worth repeating: XenonRecomp emits immediates in **decimal**, so
> `0x643C102A068A31C7` reads as `lis r9,25660` / `ori r7,r9,4138` / `lis r10,1674` /
> `ori r8,r10,12743` / `rldimi`. Searching the corpus for hex finds nothing. This is the
> same trap that hid the `.mpf` reader.

---

## `.ems` — where emitters are, and what they play

`u32 count`, then `count` records of **72 bytes**. Nothing else.

**DEMONSTRATED:** `4 + 72 * count == member length` on **all 23** members, including the two
with `count == 0`. 1,796 records in total.

```text
+0x00  u32    index       unique within a file (23/23), 1..630
+0x04  u32    flags       0 on 1,590 records; otherwise 32, 128, 224 and 11 others
+0x08  f32[3] position    x in -880..775, y in -39..231, z in -982..2992
+0x14  f32[3] extent      three floats in 1..256
+0x20  f32[4] scalars     -1..1, roles unknown
+0x30  u64    sound       name_id of the sound  <-- the event-to-sound key
+0x38  f32[4] gains       0..1; the fourth is 1.0 on every record on the disc
```

`sound` is **DEMONSTRATED** (above). The rest of the field roles are **CORROBORATED** only —
they are read from value distributions over all 1,796 records, not from a reader. The
`position` reading rests on the middle float having by far the narrowest range, which is what
a height looks like; that is suggestive, not proof, and this project has already read one
field as a duration on exactly that kind of evidence and been wrong.

The **98 unresolved** sound ids are not noise: they cluster by file. The four most-used
(502, 133, 118 and 115 records) appear only in `reverb_downtown/industrial/university.ems`,
one appears only in the three `music_*.ems`, others only in `crowds_*` or `speakers_*`. So
they almost certainly name reverb presets, music cues and speaker cues rather than banks.
Their strings are **not** in `audiofiles.big`, not in `MixMapSK8.mxb` (which contains no
strings at all), and not in the 20 MB decrypted guest image — so they are somewhere this
pass did not look, most likely the per-map world data.

## `.abk` — "ABKC", a patch bank

A fixed `0x5C`-byte header of section offsets, then four regions.

**DEMONSTRATED** — every relation below holds on **all 376** banks:

```text
0x00  'ABKC'
0x04  0x01010202                      identical on all 376
0x08  0x05030001 (369) | 0x05030002   the only variation in the header's constants
0x14  u32  = the member's exact length
0x18  u32  sample bank offset         == the word at 0x20
0x1C  u32  = 92 (0x5C)                the first section starts right after the header
0x20  u32  = 0x18
0x24  u32  = 0x30's value minus 0x18's       (i.e. the sample bank's length)
0x30  u32  patch table offset
0x34  u32  = 0x30 + 4
0x38  u32  export table offset
0x40  0xFFFFFFFF, 0x44 0xFFFFFFFF, and 0x0C/0x10/0x28/0x2C/0x3C/0x48..0x58 zero
      ordering: 0x5C < 0x18 < 0x30 <= 0x34 < 0x38 <= length
```

**The sample bank at `0x18`** is tagged **`S10A`**, on all 376:

```text
'S10A' | u32 0 | u32 count | u32 offsets[count]     offsets relative to the tag
```

`offsets[0] == 12 + 4 * count` on every bank that has any samples (two banks, `Common.abk`
and `emitter_utility.abk`, declare zero). 89,431 slots in total.

**Most of those slots are empty, and `count` is a capacity rather than a population.** Measured
2026-09-12 across all 376 banks: 5,168 slots hold a real offset and **84,263 hold
`0xFFFFFFFF`**, and no real offset ever appears after one — so the table is a fixed-capacity
array with a used prefix, not a sparse map with holes. `Abk::present()` is that prefix length and
`Abk::SAMPLE_ABSENT` is the sentinel.

Two ways that bites, both hit before it was understood. Adding the sentinel to the section base
overflows past 4 GB, so a range built from it addressed `0x10000c17f` and read like a corrupt
bank. And using it as the *next* sample's offset gives the sample before it a ~4 GB length. The
parser now refuses a sentinel slot and ends the last real sample at the section's end.

**Every real slot is a stream.** All 5,168 parse as EA Audio Core headers, and one decodes
exactly: `water_brook.abk` slot 0 is mono 48 kHz, 74,759 frames, 1.56 s. So a bank name is
enough to reach playable audio. An earlier note in the engine repo reported this as "5,168 of
89,431 parsed, a 5.8% success rate" and wondered what was wrong with the other 94%. Nothing was:
they were empty slots being counted as sounds.

**The export table at `0x38`** is the interesting one:

```text
u32 count
count x 12 bytes:  u32 target        an offset into the first section
                   u32 record        an offset to the record below
                   u32 kind
record:            u16 project_id | u16 name_id | NUL-terminated name, padded to 4
```

**DEMONSTRATED:** 1,059 records across the 376 banks parse with zero failures, giving 285
distinct names. The names are plainly a port list —

* `..._msg` — inputs. `cloth_ollie_counter_msg`, `Dist_Dog_Bark_large_msg`, `Crows_samplecntr_msg`
* `..._snd` — outputs. `cloth_popshuv_counter_snd`, `Birds_song_samplecntr_snd`
* `..._vol`, `Grit*`, `Class_*`, `Grab_*` — parameters and the object's own name

**DEMONSTRATED:** `name_id` is a pure function of the name — across all 1,059 records, no
name ever carries two different ids (285 names, 285 distinct id assignments). So it is a
name hash or a tool-assigned symbol number, not a per-file index. Which of those, and how it
is computed, is **not established**: none of djb2, CRC-32 in either bit order, FNV-1/1a, sdbm,
the Jenkins 32-bit or the low or high half of `name_id` reproduces it.

`kind` takes only **13 distinct values** over all 1,059 records, and they factor cleanly:
five low-24-bit groups (`0x414B58`, `0x3FFB58`, `0x3F8B58`, `0x57FB58`, `0x3FEB58`) each
appearing with a top byte of 0, 1 or 2. **CORROBORATED only:** the top byte correlates with
the name's role — 0 concentrates `_snd`, 2 concentrates `_msg`, 1 concentrates `c_*` object
names — but that is a correlation over suffixes, and what the low 24 bits mean is unknown.

## `.csi` — "MOIR", the authoring project's symbol table

Nine files, one per project. The header carries three counts and the project's id; then
three record tables; then a string pool.

```text
0x00  'MOIR'
0x04  0x0003 0x0100        identical on all nine
0x08  u8 5, u8 0           identical on all nine
0x0A  u16 count of table 0        table 0: 12-byte records
0x0C  u16 count of table 1        table 1: 12-byte records
0x0E  u16 count of table 2        table 2: 16-byte records
0x10  u16 project_id       0x0F52, 0x2DED, 0x167A, 0x5C48, 0x4EA6, 0x64BD, 0x69E3, 0x2E5A, 0x796A
0x28  the tables begin
12-byte record:  u32 ?      | u32 name_offset | u16 name_id | u16 ?
16-byte record:  u32 ?      | u32 value       | u32 name_offset | u16 name_id | u16 ?
```

**DEMONSTRATED.** The strides were not read off one file — they were solved as the unique
integer solution of `pool_start - 0x28 = g0*s0 + g1*s1 + g2*s2` over **all nine** files
simultaneously, giving `(12, 12, 16)` and a table origin of `0x28` rather than `0x2C`. A
12-byte-everywhere reading fits the first file's first few records perfectly and then fails
on every file: that is the reading this repo's own warning about coherent stories describes,
and the whole-distribution solve is what caught it. With the right strides the record tables
end at **exactly** the byte the string pool begins on, in all nine files, and `name_id` is
ascending within each table (so the engine can binary-search it). 662 symbols in total.

**The cross-file check, and the strongest single result here:** every `.abk` export cites a
`(project_id, name_id)` pair. Where that project ships a `.csi` in the same archive, the
project's own table resolves the id to the **identical string** — **187 agree, 0 disagree, 0
absent**. Neither file states the other's layout, so a self-consistent misreading of either
could not produce this.

The remaining **872** exports name one of six project ids for which no `.csi` ships in
`audiofiles.big` (15 project ids are cited in total, 9 are shipped). Where those projects
live is **unknown**; no `.csi` exists anywhere else in the audio data.

What the three tables *are* — and the rest of the `.csi`, which is the project graph proper —
is **not decoded**. Only the symbol table is read here.

## `.bnk` — "SPLC", a sample collection

Partially decoded; parsed far enough to be walkable, not far enough to be interesting.

```text
0x00  'SPLC'
0x04  u32 3                       on all 20
0x08  u32 payload offset          start of a region this pass does not parse
0x0C  u32 entry count
0x10  u32 ?        0x14  u32 0 (all 20)        0x18  u32 ?
0x1C  NUL-terminated name         may be empty (SK82_ConcBench_Randoms.bnk)
0x40  entry count x 36 bytes:  u16 index | u16 ? | f32[5]
```

**DEMONSTRATED** on all 20: the `0x14` zero, the name being printable ASCII, the entry table
fitting before the payload offset, and `index` running `0, 1, 2, …` with no gaps. The five
floats are **not** interpreted — the fifth is in the hundreds-to-thousands on every bank,
which is the right shape for a sample rate, but nothing here checks it against one.

Note `SK82_Dumpster_Roll_Randoms.bnk` and `SK82_Dumpster_Randoms.bnk` both carry the internal
name `SK82_Dumpster_Randoms`, so the internal name is not a unique key.

---

## So: how does a game event become a sound?

**What is demonstrated.** Audio objects are named with strings; those names are the join key,
and they appear in three places at once.

1. **The shipping executable carries the object names verbatim.** A packed string pool at
   `0x8224D700`–`0x8224DA60` in the decrypted image holds `Class_foot_drag`, `Class_grind`,
   `Class_rolling`, `c_board_slide`, `c_body_slide`, `cloth_trick`, `playercharacter_footstep`,
   `TRAFFIC_HORN`, `c_emitter`, `c_crowd_behaviour`, `c_dynamic_rolling_objects` and more,
   immediately after the pool of `data/audio/*.abk` paths it loads.
   **42 of the 285 `.abk` export names, and 82 of the 662 `.csi` symbols, are in that image
   byte for byte.** They are exactly the object-level names — `c_*` and `Class_*` — and not
   the `_msg`/`_snd` port names, which appear in no executable string.
2. **Each of those names is exported by a bank that is obviously the right one.**
   `c_body_slide` is exported by `Bodyslide.abk`; `c_board_slide` by `board_scrapes.abk`;
   `Class_grind` by `GRINDS.abk`; `TRAFFIC_HORN` by `Traffic_Horn.abk`; `Class_rolling` by
   all four `PatchBank_*` banks; `c_emitter` by 291 ambience banks.
3. **Ambient placement closes the loop by hash.** An `.ems` record carries `name_id` of a bank
   name, and that bank exports `c_emitter`. So "what plays here" is world data, resolved
   through the same hash the code uses.
4. **The loader path is visible.** `sub_824859B0` loads the AEMS projects
   (`SK8_AEMS_Foley.csi`, `Sk8_Emitters_Project.csi`, …) through the generic resource loader
   `sub_8298ED88`, storing each handle at `+504`, `+512`, `+516`, `+520` of the emitter
   system. `sub_828DC158` is the bank loader — it takes a path string and a slot number, and
   is the call `sub_824C5058` makes four times with the `PatchBank_*.abk` paths.
   `sub_824C5BF8` shows the indirect form: it takes a 64-bit `name_id`, asks `sub_82B69B08`
   for the name, `sprintf`s it through a bare `"%s"` at `0x8224A0D4`, and hands the result to
   `sub_828DC158`. **A `name_id` is resolved to a string and used as a file name.**

**Answered for the player's objects on 2026-09-14:** see "How the game addresses a player sound
object" below. What follows is the state before that.

**What is not demonstrated, and is the next piece of work.** The step from "the game decides
the board landed" to "the bank's `_msg` port fires" is **not pinned to a call site**. Two
clean negative results bound it:

* **No `.abk` port name's `name_id` appears in the lifted corpus** — 0 of 285, tested as
  `hash64`.
* **No `(project_id << 16 | name_id)` pair appears as a 32-bit constant** — 0 of 473.

### One more anchor for that search, 2026-09-13

The bank **loader** is now located, which gives the search a second thread to pull besides the
string pool. The sample bank's `S10A` tag is compared in **`sub_824967F8`** (`skate3_recomp.10`,
508 lines), and that function has exactly one caller, **`sub_824965D0`**. `sub_824967F8` reads a
type word and dispatches on it, so it is the resource loader for audio assets rather than the
trigger itself — but whatever the loader hands the engine is what a run-time port lookup must
later address, so it bounds where the routing table can be built.

Found the same way the `.mpf` reader was: **XenonRecomp emits immediates in decimal**, so `S10A`
appears as `lis r10,21297` and not as any hex spelling. Exactly one hit corpus-wide. For the next
person, the decimal forms of the tags in this document are:

| tag | constant | `lis` | `ori` |
|---|---|---|---|
| `ABKC` | `0x41424B43` | 16706 | 19267 |
| `S10A` | `0x53313041` | 21297 | 12353 |
| `MOIR` | `0x4D4F4952` | 19791 | 18770 |

`ABKC` and `MOIR` have **no** `lis` hit, which is itself informative: those tags are not built as
immediates, so they are compared against a word loaded from data, and a search for them has to
anchor on something else.

So the code does **not** hardcode port keys. It addresses the *object* (`c_body_slide`) and
the message routing lives inside the bank and its project. Whoever picks this up should start
at the string pool at `0x8224D700` and find its reader: the `addi`-from-`lis` pattern does not
reach those addresses (checked), so the base register is computed some other way, and the
functions that reference the neighbouring path pool — `sub_82486AC8`, `sub_82487168`,
`sub_82487B98`, `sub_82488120` — are where to look. The other half of the answer is the
undecoded body of the `.csi`, which is the project graph those messages run through.

## The player character's banks, 2026-09-14

The Rust engine only needs the player character's sounds (user direction, 2026-09-14), so the first
question was which banks those are. `rust/skate-audio-formats/examples/player_sounds.rs` walks every
`.abk` in `audiofiles.big` and keeps those whose exports or member names look player-side:

| object exported | bank | samples | length |
|---|---|---|---|
| `Class_rolling` | PatchBank_Rolling_Surfaces, PatchBank_Objects, PatchBank_SpiderCracks, PatchBank_RocksBounce | 16, 18, 18, 26 | 13.4, 7.0, 11.0, 3.3 s |
| `Class_wheels_skid` | WHEEL_SKID_BANK | 96 | 19.2 s |
| `Class_Flips` | Sk8_Air_Flip_Tricks | 33 | 22.4 s |
| `Class_grind` | GRINDS | 123 | 215.1 s |
| `c_board_slide` | board_scrapes | 30 | 8.2 s |
| `c_body_slide` | Bodyslide (with `bodyslide_{con,dirt,face,wood}_vol`) | 20 | 10.9 s |
| `playercharacter_footstep` | fstep_skateshoe1_sm | 192 | 55.2 s |
| `Class_foot_drag` | FOOT_DRAG | 168 | 24.5 s |
| `cloth_*`, `PC_Foley_*` | Foley_Cloth | 28 | 12.7 s |
| `Rolling_Rattle_Class` | Rolling_Rattles, probably the board | 18 | 22.7 s |

**DEMONSTRATED:** every sample in them parses as EA Audio Core **XMA, mono, 48 kHz** — a few
footsteps at 36 kHz — so the engine's existing decode path can play every one. The same walk also
matched banks that are not the skater, and they are set aside by what they export: the `TRAFFIC_*`
car banks, `c_dynamic_*` and `c_moveable_*` world objects, and two `c_emitter` ambience banks.

**Corrected the same day: "can play every one" was false for the looping ones.** A looping EAAC
header is longer than 8 bytes. It carries the loop start sample as a third word, and on a streamed
sound (`stream_type` 1, the `.snr`/`.sns` pairs) the loop block's byte offset as a fourth. The
engine skipped a fixed 8 bytes, so `GRINDS.abk` sample 0 read its zero loop start as a block header
and failed with "block size 0 does not advance".

**DEMONSTRATED on all of them:**
- 399 of the 5,168 bank samples loop, and every one of their block chains begins at +12
  (`examples/verify_loop_headers.rs`).
- All 23 16-byte `.snr` records loop with `stream_type` 1. Each loop offset is a block boundary of
  the paired `.sns`, and the block starting there holds the loop start (`verify_pairing`).
- The "8 unknown trailing bytes" of those records were these two words all along.

The engine now skips `StreamInfo::header_bytes` (engine `d88b7dc`), and that grind sample decodes
to 101,701 frames, its header's own count.

Two more archives are the skater's. `wheels.big` holds two wheel-spin loops, `Whls_spins_Jump_1`
and `Whls_spins_Man_1` (XMA mono 48 kHz, 14.81 s each, with `.sek` companions of about 90 bytes).
`grains.big` holds fourteen `.grain` files, one per surface and hardness (`asphalt_smooth_hard`,
`wood_ramp_soft`, `x_jet_rolling`, …). **DEMONSTRATED on all 14** (`examples/grain_probe.rs`): a
grain is a small table in front of an ordinary EA Audio Core stream.

```text
+0x00  u32  offset of the embedded EAAC header: 0x70, 0x90, 0xA0 or 0xB0
+0x04  f32  that stream's duration in seconds, equal to the header's own to 0.01 s (12.15 .. 21.97)
+0x08  u32  0x00100180                 identical on all 14
+0x0C  u32  0x18                       identical on all 14
+0x10  ...  a variable-length run up to the stream (x_jet_rolling's is shifted a byte), mostly
            slowly varying bytes 0x0c..0x11 -- per-grain values, not yet interpreted
+head       EAAC: XMA, mono, 44.1 kHz on nine files and 48 kHz on five
```

So the rolling sound's raw material decodes with the same path as every bank sample. **Not
established:** what the table's per-grain values mean, and how the game slices the stream into
grains by speed.

**Still open, and the harder half:** which game event fires which of these banks' ports. See the
next section's negative results; nothing here changes them.

## How the game addresses a player sound object, 2026-09-14

This answers "which game event fires which bank" for the player's objects, up to the bank's own
patch program. Read from the decrypted image (`probe/harness/out/image/`) and the lifted corpus.

**The object table.** At `0x8302D4A4` the image holds 72 entries of 8 bytes,
`{char *name; u16 project_id; u16 name_id}`. The names are the string pool at `0x8224D700` this
document already pointed at, and no `lis`/`addi` pair reaches that pool because code addresses the
*table*, not the strings.
- **DEMONSTRATED on all 72:** each `(project_id, name_id)` resolves, through the crate's
  `banks::Csi` parser (`examples/csi_dump.rs`), to the identical string.
- 55 of the entries are `.csi` group 1, 16 are group 2 and 1 is group 0.
- The player's objects are in `SK8_AEMS_skateboard.csi` (`0x64BD`): `Class_grind`,
  `Class_wheels_skid`, `Class_Flips`, `c_board_slide`, …. `c_body_slide` and
  `playercharacter_footstep` are in `SK8_AEMS_Foley.csi` (`0x5C48`), and `Class_rolling` is in
  `SK8_AEMS_rolling.csi` (`0x4EA6`).

This is why the earlier search found no `(project_id << 16 | name_id)` constant in code: the pairs
are data.

**A handle slot per entry.** Entry *i*'s handle lives at `0x8302EE28 + 8*i`, as
`{symbol record *; u32 id}`. `Class_grind` is entry 3 at `0x8302EE40`, and `Class_rolling` is
entry 42 at `0x8302EF78`. Checked on all 16 constructors below: each loads its own slot and its
own entry.

**The functions:**

| function | role |
|---|---|
| `sub_828E3250` | resolve a group-1 symbol into a slot: walk the loaded projects (list head at `0x830BBE50`), match the project id, then scan the 12-byte records for the name id **and** a string compare of the name; store the record pointer and its `+8` word |
| `sub_828E3358` | the same over the 16-byte group-2 records (17 callers) |
| `sub_828E2B48` | post a message to a slot. It checks the slot's id against the record's, allocates a 16-byte node through an allocator vtable, and calls every listener on the record's two lists as `fn(node, payload, ctx)`. Returns -6 or -3 on an empty or stale slot |
| `sub_828E2AF0` | `sub_828E2B48` under the critical section at `0x830784F0` |
| `sub_828E2730` | allocate a message (45 callers) |

**One message constructor per object.** Each fills a message, clamps its arguments to authored
ranges, posts it, and on a stale slot resolves the entry and posts again:

| object | constructor |
|---|---|
| `Class_foot_drag` | `sub_824AF498` |
| `Class_wheels_skid` | `sub_824AF678` |
| `Class_grind` | `sub_824AF8C8` |
| `Class_Flips` | `sub_824AFAD8` |
| `Class_Seams` | `sub_824AFDD0` |
| `Class_Squeaks` | `sub_824AFF48` |
| `Class_Treatment` | `sub_824B0080` |
| `Rolling_Rattle_Class` | `sub_824B0248` |
| `SenseOfSpeed_wind` | `sub_824B0388` |
| `SenseOfSpeed_rattle` | `sub_824B0520` |
| `c_board_slide` | `sub_824B0670` |
| `c_body_slide` | `sub_824B7070` |
| `cloth_trick` | `sub_824B71C0` |
| `c_cloth_falls` | `sub_824B72D8` |
| `playercharacter_footstep` | `sub_824B73E0` |
| `Class_rolling` | `sub_824C4C18` |

`Class_grind`'s, read by hand from `sub_824AF8C8`: the message is 72 bytes, `+0` receives the
posted node, and the payload handed to listeners starts at `+4`.

```text
+04 0      +08 32767   +0C..+14 0   +18 25000   +1C 0          fixed
+20 clamp(arg1, 0, 10000)           +24 1024 (fixed)
+28 clamp(arg2, 0, 14)              +2C clamp(arg3, 0, 3)
+30 clamp(arg4, 0, 32767)
+34 +38 +3C clamp(arg5..arg7, 0, 1)
+40 +44 clamp(stack args 8 and 9, 0, 32767)
```

The fixed `25000` equals group-2 symbol `send_low_pass`'s second word in the same project, and
`32767` is the common second word. So that word reads as a variable's default, but that is **not
established**. What each argument means is not read yet; the sender is.

**The senders are virtual.** `sub_824C28B0` and `sub_824C39E0` allocate a 72-byte message and call
`sub_824AF8C8`. Neither has a direct caller: both sit in a vtable at `0x822FC740`, next to
`sub_824C27D0`.

**A trap, recorded so nobody repeats it.** The image also holds `{function, 0x4000xxxx}` pairs at
`0x82338100…` that name these constructors in order. That is `.pdata`, the function-extent table,
not a dispatch table.

**Still open:** what the listener on a symbol does with the payload, i.e. the `.abk` patch program
that turns `Class_grind`'s arguments into a sample, a pitch and a gain. The listeners attach at bank
load, since an `.abk` export cites the same `(project_id, name_id)` pair.

## Also established, in passing

**The `.grain` prediction in `docs/grain-banks.md` is not supported in its strict form.**
That file predicts that if the float at `+0x04` is a duration, the fourteen floats should sort
in the same order as the members' audio lengths. Sorted by member size, the float column has
**3 adjacent inversions out of 13** — `asphalt_rough_soft` (259,699 bytes, 19.919),
`concrete_aggregate_soft` (264,090, 19.470) and `concrete_aggregate_hard` (277,434, 21.117)
each sit below a smaller member. The correlation is strong (10 of 13 in order) but it is not
the exact ordering the prediction asks for, and member size is only a proxy for audio length,
so this weakens the reading without refuting it outright. `grains.big` has no `S10A` section,
no name table and no strings — it is structurally unlike `.abk`.

## Where the code is

| what | where |
|---|---|
| `hash::member_hash`, `hash::name_id` | `rust/skate-audio-formats/src/hash.rs` |
| `banks::Abk`, `Csi`, `Ems`, `Bnk` | `rust/skate-audio-formats/src/banks.rs` |
| real-data validator | `rust/skate-audio-formats/examples/verify_banks.rs` |
| the hash, in the game | `sub_82B73AC0`, `generated/skate3_recomp.70.cpp:17945` |
| a `name_id` used as a bank name | `sub_824C5BF8`, `generated/skate3_recomp.11.cpp:52142` |
| `.csi` project loading | `sub_824859B0`, `generated/skate3_recomp.9.cpp:46610` |
| emitter ids compared in code | `sub_8255CAA8`, `generated/skate3_recomp.16.cpp:40876` |
