# Audio probe traces from played sessions

Each `LABEL.audio-trace.log.gz` holds one recomp session's audio probe lines and nothing else:
- `skate3-audio-msg`: a post to a sound object, with its payload words;
- `skate3-audio-update`: a re-delivery of a held message;
- `skate3-audio-open`: a voice open, with the sample's EAAC header words, descriptor and records;
- `skate3-audio-graph`: a voice graph build, with its module classes;
- the input script's markers and the wipeout log, when a script ran.

They are observations of the game's own audio calls: object names, payload numbers, guest addresses
and header words. They hold no audio, no game code, and no assets. Regenerate them from a full log
with the `grep -E` line in `docs/audio-banks.md` ("Trick and landing traces").

| label | how it was played | length | notes |
|---|---|---|---|
| `msgs1` | script `bail_replay_v2.txt` (2026-09-14) | 150 s | the first trace; caps then stopped the open, graph and update logs early |
| `tour1` | script `sound_tour_v1.txt` | 92 s of script | the logger kept only the last ten rotated pieces, so the boot is missing |
| `flips2` | script `late_flip_v5.txt` | 22 s of script | |
| `ollies2` | script `ollie_check_v4.txt` | 18 s of script | |
| `bails2` | script `bail_attribution_v3.txt` | 50 s of script | |
| `play1` | by hand: board slides, flips, bails | 166 s | no markers |
| `play2` | by hand: big falls, powerslides | 220 s | no markers |
| `play4` | by hand, signed in: free skate, then **Hall of Meat mode** | 13 min | no markers; Hall of Meat posts from 8:30 to 10:00 |

Read one with `probe/trace/sound_report.py probe/traces/sessions/LABEL.audio-trace.log.gz`, adding
`--every 30` for the hand-played ones. The report needs `audiofiles.big` from the user's own copy of
the game (`SKATE_AUDIOFILES`) to attribute voice opens to banks.
