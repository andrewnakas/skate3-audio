# Windows handoff

The handoff for finishing player sound on Windows lives in the engine repo:
`skate-3-rust-engine/docs/audio-player-sounds-handoff.md`. It covers where things stand, what to copy
(this repo, the audio archives, `probe/harness/out/image/`, `probe/harness/out/msgs1.log`), how to
build and reproduce the footstep result, and the remaining work order.

This repo is still the source of truth for `rust/skate-audio-core` and `rust/skate-audio-formats`,
and holds the C++ references for the remaining ports (`recomp/src/audio_ports/`).
