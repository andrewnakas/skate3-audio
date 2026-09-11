# Reproducing the derived artifacts

Nothing derived from the retail game is committed. This regenerates all of it from your
own copy. Total time is a few minutes once the recomp is built.

Assumes `skate3recomp-dev` is checked out and `game/` holds your extracted disc.

## 1. The decrypted executable image

The retail `default.xex` is AES-encrypted and LZX-compressed, so nothing is readable from
it directly. The toolchain produces the loaded image:

```sh
cd skate3recomp-dev/out/build/<preset>
ninja rexglue skate3-title-update-codegen-inputs
./sdk-out/rexglue dump-xex title_update_codegen/default.xex <outdir>
# -> default_82000000_011B0000.bin   (18,546,688 bytes, base 0x82000000)
```

**Use the patched XEX under `title_update_codegen/`**, not `game/default.xex`. The latter
dumps as title-update-less 3.0.0.0 and every address will be wrong.

## 2. Plug-in metadata and symbol names

```sh
python3 tools/rw_audio_extract.py <image.bin> --json out/rw_audio_metadata.json \
                                              --toml out/rw_audio_names.toml
```

Recovers 43 plug-ins and 30 enum types from metadata the retail build carries about
itself — the retail build has RTTI stripped, so this is the naming source.

## 3. The decompiled corpus

Needs Ghidra (`brew install ghidra` / equivalent) and JDK 21.

```sh
GH=<ghidra>/support/analyzeHeadless
$GH out/ghidra skate3 -import <image.bin> \
    -processor PowerPC:BE:64:A2ALT-32addr \
    -loader BinaryLoader -loader-baseAddr 0x82000000 -noanalysis
$GH out/ghidra skate3 -process <image>.bin -noanalysis \
    -scriptPath tools/ghidra_scripts -postScript ApplyNames out/names.csv
$GH out/ghidra skate3 -process <image>.bin -noanalysis \
    -scriptPath tools/ghidra_scripts -postScript FixHelpers
$GH out/ghidra skate3 -process <image>.bin -noanalysis \
    -scriptPath tools/ghidra_scripts -postScript DecompileAudio out/audio_funcs.txt out/decomp
```

`-noanalysis` is deliberate: entry points come from the recomp's `generated/` output, so
Ghidra's own discovery is unnecessary and slow. **Run `FixHelpers` before decompiling** —
without it every function's parameters are mis-recovered (see `docs/decompilation-status.md`).

The ~52 functions Ghidra cannot decode use VMX128; take their lifted form instead:

```sh
python3 tools/extract_lifted.py out/vmx128_funcs.txt out/lifted
```

## 4. Audio conversion

```sh
cc -O2 -o xma_decode tools/xma_decode.c $(pkg-config --cflags --libs libavcodec libavutil)
python3 tools/eaac_decode.py <archive.big> out.wav --channels 5 --rate 48000 \
                             --dump-chunks /tmp/stream
./xma_decode /tmp/stream.0.xchk /tmp/stream.0.pcm
```

Decode each chunk through **one** decoder instance. Restarting per chunk loses exactly 64
samples of MDCT overlap every time.

## 5. Reference captures

```sh
./skate3 --game_data_root=<game> --skate3_install_tu=<TU package> \
         --audio_dump_path=/tmp/guestmix.raw --audio_dump_max_frames=4000
```

256 frames x 6 channels of big-endian float32, **planar**, 6144 bytes per submit, tapped
before the 5.1→stereo fold. This is the reference for exactness; compare with
`tools/mixdiff.py`.
