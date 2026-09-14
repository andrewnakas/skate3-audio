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

**They do not need to live anywhere (2026-09-14).** The run-time lookup falls back to matching by
name id and name in any project. `rust/skate-audio-core/examples/bind_banks.rs` installs the nine
shipped projects and resolves all 1,059 exports through the Rust transcription of the lookups:
- **187** bind on the first pass;
- **868** bind on the second, by-name pass;
- **4** find nothing: `semi_horns_msg`, and `pa_announce_a_glb` twice and `pa_announce_b_glb`, from
  projects `0x0412` and `0x27CC`;
- every outcome, and the record each lands on, **agrees with an independent search** of the parsed
  files: 0 disagreements.

None of the four is a player sound.

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
| `sub_828E3250` | resolve a group-1 symbol into a slot: walk the loaded projects (list head at `0x830BBE50`) and scan each one's 12-byte records for the name id **and** a string compare of the name; store the record pointer and its `+8` word. Two passes: projects with the requested id, then, if that failed, every project. -5 when neither finds it |
| `sub_828E3358` | the same over the 16-byte group-2 records (17 callers) |
| `sub_828E2B48` | post a message to a slot. It checks the slot's id against the record's, allocates a 16-byte node through an allocator vtable, and calls every listener on the record's two lists as `fn(node, payload, ctx)`. Returns -6 or -3 on an empty or stale slot |
| `sub_828E2AF0` | `sub_828E2B48` under the critical section at `0x830784F0` |
| `sub_828E2730` | allocate a message (45 callers) |
| `sub_828E2818` | install a loaded `.csi`: turn each record's name offset into a pointer, for all three tables, and link the project into the list at `0x830BBE50`. So a record's listener head is zero on disk and filled in at run time |
| `sub_828E2C78` | release a held message: call the callbacks on its own list, drop its reference count, and free it through the allocator vtable when that reaches zero |

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

`playercharacter_footstep`'s, read by hand from `sub_824B73E0`, is 104 bytes. It has no fixed
header: the payload's first word is the first argument.

```text
+04 clamp(0, 32767)   +08 clamp(0, 65535)   +0C clamp(0, 8192)    +10 clamp(0, 1000)
+14 clamp(0, 25001)   +18 clamp(0, 25001)   +1C clamp(0, 32767)   +20 clamp(0, 32767)
+24 clamp(0, 1)       +28 clamp(0, 1000)    +2C clamp(0, 1000)    +30 clamp(0, 1)
+34 clamp(1, 4)       +38 1 (fixed)         +3C clamp(0, 1000)    +40 clamp(0, 5)
+44 clamp(1, 7)       +48 clamp(1, 5)       +4C..+64 seven fields clamp(0, 32767)
```

**The senders are virtual.** `sub_824C28B0` and `sub_824C39E0` allocate a 72-byte message and call
`sub_824AF8C8`. Neither has a direct caller: both sit in a vtable at `0x822FC740`, next to
`sub_824C27D0`.

**A message is a held instance, not a one-shot event.** In `sub_824C28B0` (`this` is the grind
sound component, `obj = *(this+32)`):
- The message is built only while `this+36` holds no handle and `obj+341` is set. The handle is kept
  at `this+36`, and a second one at `this+40`.
- When `obj+341` clears, both are released through `sub_828E2C78` and freed through `sub_828E27B0`.
- So `obj+341` reads as "grinding", and the message lives for the grind.

Where `Class_grind`'s arguments come from:

| arg | source |
|---|---|
| 1 | `min(9000, int(clamp((obj+208 - 0.5) / D * 3.6, 0, 1) * 10000))`. `obj+208` is a speed and `3.6` converts m/s to km/h. `D` is a tuning float looked up by id `0x4890392C91829954` |
| 2 | a surface class: `sub_82494E18(obj+692)` reads `+16` of material *n*'s entry (94 materials), or 4 when the material is 143. A class of 14 means no grind sound at all |
| 3 | a grind variant from `obj+192`: 1, 2 or 4 give 0; 5 gives 3; anything else gives 2 |
| 4 | `sub_824C2E48(class, variant)`: `int(tuning float * 32767)`. The float is chosen by a per-class 64-bit id (a 15-entry table at `0x82249F90`) and one of four keys by variant, so it reads as a per-surface, per-variant level |
| 5 | 1 when a check against id `0x11A631798B239355` passes |
| 6, 7 | flags from `*(this+16)`: `+72` set (7), and also `+64` zero (6) |
| 8 | when 7 is set, the component's virtual call at vtable `+60` with argument 6 |
| 9 | the word returned by `sub_824B7A40` |

When `obj+192` is 0, a second `Class_grind` message is sent with variant 1 and its own level.

**The tuning ids are not image strings.** `examples/resolve_ids.rs` hashes every printable run in
the dumped image with `name_id`:
- none of the 23 ids above resolves;
- its positive controls do: `StateGraph`, `challenges` and `default`.

So those names live in game data, not in the executable.

**A trap, recorded so nobody repeats it.** The image also holds `{function, 0x4000xxxx}` pairs at
`0x82338100…` that name these constructors in order. That is `.pdata`, the function-extent table,
not a dispatch table.

**The banks cite the same name ids, but not always the same project.** Measured over every `.abk`
export of the 17 player objects the game table names (`examples/export_projects.rs`):
- 22 exports, and the `name_id` agrees with the game's table on **all 22**.
- The project id agrees on 15: `Class_rolling` ×6, `playercharacter_footstep`, `Class_foot_drag`,
  `Class_wheels_skid`, and others.
- It differs on 7. `Class_grind`, `Class_Flips`, `Class_Squeaks`, `c_board_slide` and both
  `SenseOfSpeed_*` cite `0x63D9` where the game uses `0x64BD`, and `c_body_slide` cites `0x4228`
  where the game uses `0x5C48`.
- Neither `0x63D9` nor `0x4228` ships a `.csi`.

**Corrected the same day: they do bind.** The lookups make **two passes** over the loaded
projects. The first requires the project id to match. If it finds nothing, the second ignores the
project and matches the name id and the name string alone (`sub_828E3250`'s `r29` flag, read from
labelled blocks). So `GRINDS.abk`'s `0x63D9:0x09C5` export binds to `SK8_AEMS_skateboard`'s
`Class_grind`. The paragraph that stood here said those banks could not bind, which was a misreading
of one branch.

## From a message to the evaluator, 2026-09-14

**This closes the chain from a game event to running audio code.** The "patch program" is the
expression evaluator that `rust/skate-audio-core/src/eval/mod.rs` already documents (40 opcode
slots at `0x82FD3600`, interpreter `sub_82B1E290`). What was missing was how a bank's program gets
onto the interpreter's node list. Read from the lifted code:

**Installing a bank: `sub_82B1DF50`** (load thread).
1. It rewrites code references in the bank: each listed word holds an opcode index and becomes
   `TABLE[index] - address - 4`.
2. It rebases the offset lists.
3. It resolves every export into a slot *inside the bank* through the `.csi` lookups. The export's
   `kind` top byte picks the table: 0 means `sub_828E3358` (group 2), 1 means `sub_828E3250`
   (group 1), and 2 means `sub_828E3148` (group 0). That explains the earlier correlation of the
   top byte with `_snd`, `c_*` and `_msg` names.
4. For each input record whose slot resolved, it links a listener node onto the symbol record:
   function `sub_82B1DAD0`, context the input record.

**Input records**, counted by the header's u16 at `+0x0A` and starting at the offset at `+0x1C`:

```text
+04  slot {symbol record*, id}     an export resolves into it
+14  listener node {next, prev, fn = sub_82B1DAD0, ctx = this record}
+1C  u16 live instances            +1E  u16 capacity
+20  u16, +22 u16                  counts of two further entry lists sub_82B1D880 links
+24  u8, u8, u8, u8                +24 and +27 count the u32 entries that follow +3C
+28  offset copied to each instance's +10 (the program)
+2C  instance template offset      +30  instance size        +34  back-pointer offset
+38  live instance list
+3C  u32 entries, 4 bytes each
```

**DEMONSTRATED on all 376 banks** (`examples/verify_patch_records.rs`):
- 385 input records, 0 failures.
- Every record's `+04` is the target of **exactly one** export, and all 385 of those exports have
  kind top byte 1, the group-1 objects the game posts to.
- The other 674 exports (top byte 0: 362; 2: 311; 1: 1) bind slots elsewhere in the program.
- Every template lies inside the first section, and `+28` points past the records on all 385. It
  is the very next byte on 369, which is why it first read as "the next region".
- Capacities are mostly 10 (300 records), then 1 (30) and 16 (28). `GRINDS.abk` has one record of
  capacity 4 with a 2,500-byte template.

**The installer's fixup lists, DEMONSTRATED on all 376 banks** (`examples/verify_bank_fixups.rs`):
- The code-reference list at the header's `+0x30` is empty on every bank.
- The rebase list at `+0x34` holds 4,656 words, each an offset inside its bank's first section.

**A post spawns an instance.** The listener `sub_82B1DAD0` checks live < capacity, then calls
`sub_82B1D880`, which:
- allocates the instance and copies the template;
- links the instance onto the record's live list;
- threads the instance's evaluator nodes, wiring them to the posted message's lists;
- links the instance onto the interpreter's node list at `0x83036F4C`.

Opcode slot 4, `sub_82B1C150`, is the reverse: it unlinks an instance from both lists and frees it.

**The programs themselves, DEMONSTRATED on all 376 banks** (`examples/verify_patch_programs.rs`):
- A record's program at `+28` parses as `{u8 op, u8 pairs, u16, pairs x {i32 src, i32 dst},
  i32 advance}`, ending at opcode 255.
- 385 programs, 31,016 ops (longest 879), **0 failures**. Every opcode is below 40.
- Every pair's offsets, relative to the current block and sometimes negative, stay inside the
  operand area.
- The block pointer finishes **exactly** at the end of that area (`size - 24`) on all 385.
- Programs share a frame: they open with op 0, then 2 or 1, then 3, and 360 of the 385 close with
  `[27, 4]` or `[5, 4]`.

Opcode use across all programs: 19 never, 38 once, 9 three times; 10, 15, 17 and 35 over 2,000
each. The player banks use every ported slot plus six unported ones:

| slot | function | used by | what it is |
|---|---|---|---|
| 1 | `sub_82832BA8` | all 385 | `return block[20]`, one instruction, shared by identical-code folding with game code |
| 2 | `sub_82C8CDC8` | 252 | `return block[24]`, likewise |
| 4 | `sub_82B1C150` | all 385 | end the instance: unlink from both lists and free |
| 5 | `sub_82B1C210` | 182 | clamp a value block and broadcast it (C++ body pending) |
| 27 | `sub_82B1D240` | 1,527 ops, every player bank | **the voice op**. `block[24]`, clamped to 0..2, is the requested state. State 0 releases the voice at `block+8`. State 1 picks entry `clamp(block[20])` of the table at `block+4`, whose u16 at `+4` is a sample id (`0xFFFF` means none), starts it through `sub_82B1F4C8`, and updates it through `sub_82B1F5F8` and the voice's vtable `+24` |
| 39 | `sub_82B1C450` | `Foley_Cloth` only | notify a handler list |

**The allocator's callbacks** (addresses computed, then read):

| address | role |
|---|---|
| `sub_82B1D7F8` | set `+16` = 1 when the posted message is released |
| `sub_82B1D7E8` | copy a registered value into `+24` |
| `sub_82B1D808` | copy the posted message's payload words into the entry. This is how `Class_grind`'s arguments reach the program's operand block |
| `sub_82B1D840` | the same for messages the instance subscribes to (the `+22` list), setting `+25` = 1 on arrival |

**Where a patch meets the voice system (read 2026-09-14).** Slot 27 opens its voice through
`sub_82B1F4C8`, which calls slot 0 of the device singleton at `0x82FD35F8`.
- **The device.** The boot-time image holds a fallback object there (`0x83036F48`). Game init
  (`sub_826D4C30`) replaces it with the static device at `0x8302F068`, vtable `0x822FBC9C`. Slot 0 of
  that vtable is `sub_824A3140`, 693 instructions on the game thread.
- **The open call's arguments** name a sample, which means a bank sample and its playback
  parameters:
  - `r4` is `table + table[s16 index + 3]`, where the table is `*(config+64)`. The config is the
    bank itself, via the back-pointer the installer wrote into the template, and `+64` is the sample
    bank pointer `load_bank` sets. So `r4` points at an EA Audio Core stream inside the bank's
    `S10A` section: the index skips the section's three header words.
  - The rest: a byte, six descriptor bytes shifted up a byte, the bank's `+72`, `+76` plus the
    descriptor's `+8` word, and the op's `{count, records}` parameter block.
- **What `sub_824A3140` does.** It allocates a 104-byte voice and builds a mixer graph for it
  through the audio system (`sub_82B48C48`, `sub_82B46260`, and module vtables). That graph is the
  ported Phase 4 code, so this is the seam between a patch and the mixer.
- **The parameter pushes.** `sub_82B1BE30` clamps a property id and value and tail-calls the
  voice's own setter at vtable `+12` (or `+16` for id 3).

**Correction to the interpreter's period.** The image dump's `0x82FD35F4` reads 41.6, but that is a
boot-time value: the same game init stores 30.0 there (from `0x820D4924`) and zeroes the delta
cache. So in play an evaluator period is 1/30 s. With 256-sample frames at 48 kHz, that is 6
frames.

**A grind program, run (2026-09-14).** With the whole chain in Rust (`patch.rs`, `voice.rs`,
`eval/`), one `Class_grind` post with speed 5000, surface class 3, variant 0 and level 20000 makes
the real `GRINDS.abk` program:
- open **two looping voices**, bank samples **41** and **40** (48 kHz mono, 65,718 and 70,161
  samples), each with descriptor byte 80;
- push the same 11 parameter records to each: `0 = 0, 2 = 0, 3 = 0, 5 = 0, 6 = 25000, 7 = 0,
  8 = 32767, 9 = 4096, 10..12 = 0`.

Read at face value, 6 matches `send_low_pass`'s 25000 default, 8 a full volume and 9 a unit pitch in
12-bit fixed point. **None of that is established**; the run is against a logging device, not the
game.

**What the property ids do, read from the voice's own setters (2026-09-14).** The voice
`sub_824A3140` returns has vtable `0x822FBCA8`. Its `+12` setter `sub_824A29A8(id, value)` posts
each change as a command to the audio thread. The handler is `0x82B463A8`, the verified
parameter-slot stamp in `rust/skate-audio-core/src/leaves.rs`, so a property is a module parameter
write inside the ported graph.

| id | effect |
|---|---|
| 0 | module at voice `+12`, parameter 0 = `value / 4096` |
| 2 | stored as `value / 32767` at voice `+40`; the gains below are multiplied by it |
| 5 | stored as `value / 32767` at `+48`; module `+24` gets `+48 × +40` |
| 8 | stored as `value / 32767` at `+44`; module `+28` gets `+44 × +40` |
| 6 | module `+20`, parameter 0 = `value` as a float (25000 reads as a cutoff in Hz) |
| 7 | module `+16`, parameter 0 = `value` as a float |
| 11 | module `+84`, parameter 0 = `value / 32767`, only when `+88` is set |
| 3 | the alternate setter `sub_824A2C58`: module `+32`, parameters 7 and 8 to constants, then parameter 0 = `value × 360/65536`, i.e. degrees |
| 1, 4, 9, 10, 12 and above, except 11 | no effect in this setter |

So ids 5 and 8 are two gains under a master gain (id 2). In the logged grind run id 2 was **0**, and
the reason is now read: **the first post is silent by design, and the game's per-frame update makes
it audible.**

- **Why the first post is silent.** The grind program computes each voice's master gain as
  `round(level × (word0 − s) × band weight / 32767²)`. Here `s` is a value the two flag arguments
  select, and the band weight is one of three speed-mapped ramps (for speed 5000: 0, 27306 and
  6553). The constructor `sub_824AF8C8` posts word 0 as **0**.
- **What the update does.** Every frame, for both held grind messages, `sub_824C39E0` rewrites the
  payload and re-delivers it through **`sub_828E2D18`**, which runs the post node's payload
  callbacks again. It writes:

  | field | value |
  |---|---|
  | `+4` (word 0) | 32767 |
  | `+8` | a volume, clamped to 32767 |
  | `+12` | clamped to 32767 |
  | `+16` | clamped to 65536 |
  | `+20` | clamped to 8192 |
  | `+24`, `+28` | two values clamped to 25000 |
  | `+32` | the speed, clamped to 10000 |
  | `+44` | the variant |
  | `+64` | clamped to 32767 |

- **The Rust run with those updates** (`UPDATES=1 cargo run --example grind_instance`: word 0 =
  32767, volume 20000, both cutoffs 25000, speed 5000). By frame 23 the two open voices' master
  gains are 2441 and 7068, a third voice opens with 6553, and id 8 follows the volume (20000).
- **What stays unverified.** The update values are chosen here, not the game's. The re-delivery
  probe (`skate3-audio-update` lines) records real ones in the pending session. The query `sub_824A2DD8` reports a voice finished (first word 0) when
its player's `+71` byte is 2.

**What this means for the Rust engine.** A player sound needs four pieces:
- a bank installer;
- the post, listener and instance allocator;
- the interpreter `sub_82B1E290`;
- the 40 opcodes.

Only the opcodes are transcription (31 ported). The interpreter fails the port screen's gates 1
and 2, and the installer and allocator run on the load and game threads, outside the 216. So those
three are new work, checkable against traces rather than against a verified C++ body.

**The project mismatch does not stop binding.** The installer resolves a record's slot through
`sub_828E3250`, whose second pass ignores the project id. So a `GRINDS.abk` built against `0x63D9`
binds by name to the `0x64BD` symbol the game posts to. The message probe's `listeners=` column will
confirm it at run time.

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
