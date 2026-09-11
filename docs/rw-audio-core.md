# RenderWare Audio in Skate 3 — decompilation notes

Working notes for the audio decompilation. Every claim below is backed by the retail
image; addresses are guest addresses in the **title-update-3** build
(`XEX patch applied: base version 3.0.0.0 -> new version 3.0.3.0`), which is the build
the recomp lifts and the one `skate-data`'s existing modules cite.

## How to reproduce the image

The retail `default.xex` is AES-128-CBC encrypted and LZX compressed, so nothing is
readable from it directly. The toolchain can produce the loaded image:

```sh
cd skate3recomp-dev/out/build/macos-fast
ninja rexglue skate3-title-update-codegen-inputs
./sdk-out/rexglue dump-xex title_update_codegen/default.xex <outdir>
# -> <outdir>/default_82000000_011B0000.bin   (18,546,688 bytes, base 0x82000000)
```

Use the **patched** XEX under `title_update_codegen/`, not `game/default.xex` — the
latter dumps as TU-less 3.0.0.0 and its addresses will not match `generated/`.

## RTTI is not available

The retail build was compiled with RTTI disabled: a scan for MSVC type descriptors
(`.?AV…@@` / `.?AU…@@`) over the whole image returns **zero** matches. Class names
cannot be recovered that way.

They do not need to be. RenderWare Audio is **self-describing**, and that metadata
turns out to be richer than RTTI would have been.

## The plug-in metadata system

The audio engine is a graph of plug-ins. Every plug-in ships a descriptor carrying a
4CC tag, a name, function pointers, and tables describing its attributes, events,
parameters and enums — each with an identifier, a display name, and prose
documentation written for a tools UI. All of it is in `.rdata` in the shipping build.

Descriptor layouts recovered from the image (big-endian throughout):

```
enum value    +0 char* identifier   +4 char* display   +8 char* doc   +12 u32 value
enum type     +0 char* name         +4 char* doc       +8 u32 count   +12 EnumValue*
plug-in       +0 char* name         +4 fn*             +8 fn*         … +N u32 4CC
```

Worked example, the `Format` enum at `0x82FD0DE0` pointing at values from `0x82FD0DC0`:

```
82FD0DC0: "FORMAT_16BIT_INT_LE"     "16 bit interleaved little endian"        … 0
82FD0DD0: "FORMAT_FLOAT_INT_NATIVE" "Floating point interleaved host native"  … 1
82FD0DE0: "Format"  "The Format is used to specify the encoding of…"  count=2  →82FD0DC0
```

`tools/rw_audio_extract.py` walks these tables and emits `out/rw_audio_metadata.json`
plus a rexglue `[functions]` name table. It recovers **43 plug-ins and 30 enum types**
in about 7 seconds.

## Plug-in inventory

The 4CC convention is a three-symbol mnemonic plus a version digit: `PPl0` PacketPlayer,
`MtP0` MatrixPanner, `RM10` ReverbModel1, `Sub0` SubMix.

Sources: `PacketPlayer`, `GenericPlayer`, `HwPlayer`, `SinePlayer`.
Filters: `BandPassFir64`, `BandPassIir2`, `HighPassIir2`, `LowPassIir2`,
`HighPassFir64`, `LowPassFir64`, `HighPassButterworth`, `LowPassButterworth`,
`HighShelfIir2`, `LowShelfIir2`, `PeakingIir2`.
Dynamics and shaping: `Compressor1`, `Limiter1`, `DistortionClip`, `Gain`, `GainFader`,
`HwGain`, `Delay`, `TimeStretch`, `FrequencyShiftSsb`, `Resample`, `ResampleHQ`.
Spatial and routing: `MatrixPanner`, `Pan3D`, `HwPan2D`, `SubMix`, `Route`, `Send`,
`Rechannel`, `MapChannels`, `Dac`, `HwFxReturn`, `ReverbModel1`.
Utility: `Pause`, `VuMeter`, `SampleCapture`, `AiffWriter`, `UserMusicArbiter`,
`WiiRemoteSpeaker`.

`WiiRemoteSpeaker` and `AiffWriter` are cross-platform leftovers, not used on Xbox 360.

Filter families **share implementations**, which matters when naming functions —
emitting one entry per plug-in would produce duplicate TOML keys:

```
82B261E0 / 82B26208   HighPassButterworth + LowPassButterworth
82B263D0 / 82B263E0   HighPassFir64       + LowPassFir64
82B27D18 / 82B27D20   HighPassIir2        + LowPassIir2
82B27F78              BandPassIir2 + HighShelfIir2 + LowShelfIir2
```

The two pointer slots are recorded as `f0`/`f1`; what they dispatch to is **not yet
established**, so the generated names do not claim otherwise.

## `P6L0` and `PFN0` — resolved

These are the two entries of the codec tag table at `0x8210A310` that
`src/skate3_audio_fixes.cpp` indexes with the byte at `Player+352`. They had been
carried as unidentified. The image settles it — the tags sit immediately before the
`Format` enum's strings in the same `.rdata` pool:

```
8210A310: 50 36 4C 30  50 46 4E 30  "PacketPlayer\0"
          'P6L0'       'PFN0'
8210A35C: "FORMAT_16BIT_INT_LE"     "16 bit interleaved little endian"
8210A404: "FORMAT_FLOAT_INT_NATIVE" "Floating point interleaved host native"
```

The `Format` enum has exactly two values, 0 and 1, matching the two valid index bytes
the recomp already observed:

| index | tag | format |
|---|---|---|
| 0 | `P6L0` | 16-bit interleaved little-endian PCM |
| 1 | `PFN0` | 32-bit float interleaved host-native PCM |

Read against the `PPl0` convention the mnemonics are plain: **P**CM **16** **L**E, and
**P**CM **F**loat **N**ative.

**They are PCM formats, not compressed codecs.** That fixes the architecture: the
on-disc EAAC codec-3 XMA is decoded by the hardware XMA contexts, and the resulting
PCM is submitted to `PacketPlayer` in one of these two layouts. So the pipeline is

```
.snr/.sns (EAAC codec 3, XMA)  ->  hardware XMA context  ->  PCM
   ->  PacketPlayer (P6L0 | PFN0)  ->  plug-in graph (panners, filters, submix)
   ->  XAudioSubmitRenderDriverFrame
```

`PacketPlayer` is documented in the image as a FIFO of submitted packets, driven by
`EVENT_PLAY` / `EVENT_SUBMIT` / `EVENT_STOP` / `EVENT_ISPACKETDONE`, with all events
asynchronous — which is precisely the command queue whose unlocked append is bug 1.

## The `0x8210A310` corruption — source identified

The 32 bytes that overwrite the tag table are a fragment of a plug-in **documentation
string**. The full sentence lives in the `BandPassIir2` description at `0x820EEBE0`,
and the corrupting fragment begins 226 bytes into it, mid-word at the `d` of
"feed-forward":

```
820EECC2   "d-forward and feed-back elements"   (exactly 32 bytes)
```

Five other IIR plug-in descriptions contain the same phrase, so the specific source is
not yet pinned to one:

```
820EECC2  (+226 into 820EEBE0)     820FE40A  (+226 into 820FE328)
820FEBC8  (+696 into 820FE910)     821077F0  (+224 into 82107710)
82107F93  (+643 into 82107D10)     8210EE0D  (+597 into 8210EBB8)
```

Two things follow. The write is a **fixed-length 32-byte copy**, not a `strcpy` — it
neither stops at nor appends a NUL. And 32 is exactly the length of a display-name
field in this metadata (`"16 bit interleaved little endian"` is also 32 bytes). So the
shape is a fixed-size description/name field being copied to a wrong destination, with
a source pointer already offset into a longer string.

This also confirms the existing reading that the `'rwar'` testers see at index 1 is
bytes 4–7 of that sentence, not a RenderWare FourCC. There is no `rwar` tag anywhere in
the game data.

## Function names recovered so far: 114

`tools/rw_audio_extract.py --toml` emits a rexglue `[functions]` table. Two sources:

1. The two function pointers inline in each plug-in record (+4, +8).
2. A further ~44 reachable through the record's four pointers at +12..+24, which lead
   into a region of attribute default/min/max constants with a few functions among them.

Names are mechanical — `rwaudio_<Plugin>_<address>`, with shared functions naming every
user (`rwaudio_DistortionClip_HwGain_82B26978`). What the slots *do* is still unknown, so
nothing claims otherwise. Deduplicated by address: emitting per plug-in would produce
duplicate TOML keys and break codegen.

### Negative result: the attribute/event tables hold no code

Attribute, event and parameter descriptors are 16 bytes of pure metadata —
`{identifier, displayName, doc, value}` — with **no handler function pointers**. Events
are `{identifier, paramTypeName, displayName, doc}`. So this metadata cannot be mined for
further function names; it is a naming source for *data*, not code. Worth recording so
nobody spends another pass on it.

### The audio band is wider than assumed

Two plug-in functions fall outside `0x82B00000`–`0x82B87000`:

```
Gain        fn1 = 0x82671F50
HwFxReturn  fn1 = 0x82D0EBB8
```

`sub_82D19648`, the named-object lookup, was already known to sit out at `0x82D1xxxx`.
So the band is not a single contiguous range, and any "decompile everything in the band"
pass must either widen its bounds or work from the call graph instead of an address
window. The 1,322-function figure is a floor, not the true count.

## Status

Done: image extraction, plug-in and enum inventory, `P6L0`/`PFN0`, corruption source,
name table for 70 audio functions.

Next: establish what the `f0`/`f1` slots are, walk the attribute/event/param tables to
name the per-plug-in entry points, and pin the corrupting copy to one call site.
