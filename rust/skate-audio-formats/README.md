# skate-audio-formats

Parsing for Skate 3's audio containers. Byte handling and bounds checks only — codec
arithmetic belongs elsewhere, matching the split the engine's existing `abin` module states.

- `eb` — EA "EB" v3 archives
- `eaac` — EA Audio Core stream headers, block chains, chunk splitting, `.sth` sub-sounds
- `mus` — interactive-music segments

`cargo test` runs 28 unit tests. Those use synthetic payloads and prove only self-consistency;
the `examples/verify_*.rs` programs run the same code over real archives and are what
actually find bugs. Point them at your own copy of the game.
