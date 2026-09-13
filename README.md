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

## What is done

**The audio engine now exists twice: as the recompiled original, and as readable native C++
that has been proved equal to it call for call.**

| | status |
|---|---|
| Audio subsystem decompiled | 1,694 functions, full coverage, call-graph bounded |
| Structure layouts | 7 structs, 35 machine-checked offsets (`docs/rw_audio_structs.h`) |
| Container formats | all three decoded — `.sns`, `.dat`, `.mus` |
| Audio conversion | **sample-exact** on all three classes |
| Real-data coverage | 33,448 speech sub-sounds, 8,179 music segments, 1,384 ambience blocks |
| **Native C++ port** | **all 216 audio-thread functions written; 138 shadow-verified, zero divergence** |
| Exactness harness | shadow verification, per-call, against the running game |
| Rust container parsing | `skate-audio-formats`, 33 tests, validated on real archives |
| Rust queue path | `skate-audio-core`, 79 tests over 36 functions, 8,607/8,607 recorded vectors replayed |
| **Audio in the Rust engine** | **plays real game streams**: decoded byte-exactly, fed to a Bevy audio source, and confirmed reaching the sound card by recording the output device |

### The native port, in one table

The 216 functions are those first called on the `RwAudioCore Dac` thread during play —
the set that is actually audio and actually runs. Every one has a body; 138 of them are
*proved* equal to the original, and the rest carry the reason they cannot be:

| outcome | count | meaning |
|---|---|---|
| verified | **124** | zero divergence, on enough calls for their size to carry promotion |
| verified but thin | 14 | zero divergence, but on too few calls for their size — held out of default promotion (`docs/promotion.md`) |
| partial | 9 | one path compares clean, another is declined and never compared — never promotable |
| gate 1 | 62 | reaches an indirect call, lock, allocation or release, so replaying it on rewound memory is unsound |
| gate 2 | 2 | write set not derivable from entry state |
| gate 3 | 3 | reads `mftb`, so two runs return two values and no comparison can pass |
| pre-existing | 2 | hooked before this work (`EVENT_STOP`, the XMA probe) |

Nine of the gate-1 group were later given window builders that decline only the uncomparable
path, which is how the count fell from 69: a gate is often a property of one path, not of the
function. `docs/port-loop.md` has the measured split.

A gate is a property of the function, not a gap in the work. Each gated port still has a
readable body and a note recording the write set it *would* have declared.

Final verification, all 214 port files armed in one binary:

| session | result |
|---|---|
| boot profile | 214 expected, 0 not green |
| scripted skate and bail | 214 expected, 0 not green; **73.5M** counted calls |
| promoted (`--skate3_audio_native=true`) | **138 native bodies ran for real**, audio 187.5 frames/s, no crash, capture matched its layout |

Two results worth more than the port count. `sub_824531C8` — a four-lane sine kernel with no
stores, whose result lives in a volatile vector register — verified over **6,994,118 calls**
once the harness could compare arbitrary registers; under the old scheme that comparison
checked nothing at all. And reading these bodies found a **second producer** of the command
queue carrying the same publish-before-store race as the known bug, which means a fix confined
to one function cannot close it (`docs/command-queue.md`).

## What is next

In rough order of value:

1. ~~**Promotion.**~~ **Decided and enforced** (`docs/promotion.md`): promote a verified body when
   its weaker profile compared at least one call per lifted line and at least 100 calls. That is
   124 of 138; the other 14 carry `kPortVerifiedThin`, which shadows but can never be promoted.
   Confirmed in a promoted session — exactly 124 native bodies ran, audio at 187.5 frames a second
   with zero silent submits. The cvar still defaults to false; flipping it is the recomp owner's
   call.
2. **The Rust audio engine** (`docs/PLAN.md` Phase 4). Every function the Rust port needs now has
   a verified C++ reference, which turns each translation into a transcription risk rather than a
   semantic one. `skate-audio-core` has the queue path and the expression evaluator; the
   scheduler, XMA feed and DSP graph are not written.

   **Playback works and has been measured at the sound card.** `skate-3-rust-engine` reads a
   retail archive member, decodes it byte-exactly against an independent reference, and plays it
   through a Bevy audio source. `skate3-audio-check` runs that path with no window, renderer or
   assets, which is how it was verified on a checkout the game itself will not boot on:

   | measurement | result |
   |---|---|
   | decode | 306,816 frames of 5 channels (6.39 s) in 0.19 s, zero deficit |
   | recorded level, before then during | about -58 dBFS, then about -45 dBFS |
   | cross-correlation peak | lag 1.370 s, peak-to-mean **58.8** |
   | time-reversed control | peak-to-mean **5.7**, at a lag outside the overlap |

   The lag is the recorder's head start plus the program's startup, so the sound card received
   the audio the decoder produced. Two weaker tests failed first and are worth knowing about: an
   envelope correlation cannot fingerprint a steady ambience bed, and a whole log-spectrum
   correlation scores ~0.85 on *any* two audio signals.

   **What is still missing is the choice of stream.** The metadata table that maps a sound to a
   map or an event is not decoded, so a stream is named by hand
   (`SKATE_AUDIO_PLAY=archive:entry:channels:rate`). That table is the next piece of real work on
   the engine side.
3. **`.mpf` sequencing**, sections 0–3. Interactive music needs segments *plus* the map that
   orders them. The `.mus` side is complete; this is the headline format gap
   (`docs/xma-transcode.md`, and the live lead in the guest image).
4. **Bug 1's ordering fix**, now that **at least fourteen** producers are known, on three measured
   threads. A corpus-wide search (`probe/screen/find_producers.py`) found thirteen append sites
   beyond the two that were read by hand, every one publishing the write offset before storing the
   record. Three of them ran on the render, audio and load threads in the traced sessions, so the
   concurrency is measured rather than argued. The discipline has to land at every site, most of
   which sit outside the 216 ported functions, and eleven have never been observed executing at
   all. `docs/command-queue.md` has the list and the two limits on it.
5. **Codec in-crate.** The engine decodes exactly today, but through the `ffmpeg` binary: XMA2 is
   a hardware codec and `libavcodec` is the only free implementation of it. A pure-Rust decoder
   would remove the last external dependency in the audio path. `tools/xma_vectors.py` builds
   per-chunk vectors for checking one, and `docs/xma-transcode.md` records why those vectors pin
   only a stream's first chunk.

Explicitly **not** planned: ARM64 bit-exactness for the Rust port, a general-purpose XMA
toolkit, and root-causing the two recomp bugs on QCS8550 hardware nobody here has. See
`docs/PLAN.md` non-goals.

## Layout

```
docs/     analysis: the engine, command queue, bugs, formats, struct header, port results
tools/    extraction, decoding, verification and source-sync tooling
rust/     skate-audio-formats (containers) and skate-audio-core (the ported engine)
recomp/   sources to drop into the recomp: probe, shadow harness, 214 native ports
probe/    the port loop: static screening, the queue, session running, log summarising
```

Two documents carry the port work: `docs/port-loop.md` explains how the sweep was run and what
it cost to learn, and `docs/ports.md` is the generated per-function status table.

Start with `CLAUDE.md` if you are an agent picking this up, or `docs/` if you are not.
