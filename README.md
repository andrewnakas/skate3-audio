# skate3-audio

Reverse-engineering of Skate 3's audio system, and tools to convert its audio.

Skate 3 uses **RenderWare Audio** (`rw::audio::core`) — EA's in-house middleware — driving
the Xbox 360's hardware XMA decoder contexts directly and pushing mixed frames through the
low-level `XAudioRegisterRenderDriverClient` / `XAudioSubmitRenderDriverFrame` path. Not
XACT, and not the XAudio2 voice API.

This repository serves two consumers:

- **[skate3recomp](https://github.com/andrewnakas/rexglue-skate3)** — a RexGlue static
  recompilation of the retail XEX. Its audio already works (it *is* the original code), so
  the value here is understanding it well enough to fix and to port.
- **[skate-3-rust-engine](https://github.com/SK8-ENGINE/skate-3-rust-engine)** — a
  clean-room Rust/Bevy reimplementation with no audio yet. `rust/skate-audio-formats` is
  intended to be consumed there.

## No game content here

This repo contains tools, documentation and original code only. It deliberately excludes:

- the decompiled function corpus and lifted C++ (derived from the retail executable)
- decoded audio and mixer captures
- any part of the game itself

Everything derived is **reproducible in minutes** from your own copy of the game — see
`docs/REPRODUCING.md`. This matches the posture of both projects above, which ship no
retail content either.

## What works

| | status |
|---|---|
| Audio subsystem decompiled | 1,694 functions, full coverage, call-graph bounded |
| Structure layouts | 7 structs, 35 machine-checked offsets (`docs/rw_audio_structs.h`) |
| Container formats | all three decoded — `.sns`, `.dat`, `.mus` |
| Audio conversion | **sample-exact** on all three classes |
| Real-data coverage | 33,448 speech sub-sounds, 8,179 music segments, 1,384 ambience blocks |
| Rust container parsing | 33 tests, validated against real archives |
| Exactness harness | shadow verification + bit-exact mixer comparator |

## Layout

```
docs/     analysis: the engine, command queue, bugs, formats, struct header
tools/    extraction, decoding and verification tooling
rust/     skate-audio-formats — container parsing crate
recomp/   sources to drop into the recomp: probe, shadow harness, native audio
```

Start with `CLAUDE.md` if you are an agent picking this up, or `docs/` if you are not.
