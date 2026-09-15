# Windows handoff

The handoff for finishing player sound on Windows is in the engine repo:
`skate-3-rust-engine/docs/audio-player-sounds-handoff.md`. It covers:
- where things stand, and the target table of every player sound object;
- the recorded sessions, which are in this repo under `probe/traces/sessions/`, with
  `probe/trace/sound_report.py` to read them;
- what to copy by hand: the audio archives, and `probe/harness/out/image/`, which must never be
  committed;
- how to build and reproduce the footstep result;
- the remaining work order.

This repo is still the source of truth for `rust/skate-audio-core` and `rust/skate-audio-formats`,
and holds the C++ references for the remaining ports (`recomp/src/audio_ports/`). Recording new
traces is Linux-only (`probe/harness/run_session.sh` with `SIGNED_IN=true`, plus
`probe/trace/keep_log_pieces.sh`).
