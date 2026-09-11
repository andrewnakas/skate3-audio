# Driving the game without a player

A traced session has to cover what a player does — skating, bails, the replay editor — and
the recomp's boot automation only taps buttons. Skate's tricks are right-stick flicks, so
button taps cannot skate, trick or bail. This harness replays a scripted pad timeline
instead, and records what the game decided.

Built on prior work in sibling projects on this machine: `sk8-engine-linux`'s input lab
supplied the bail signal, and `skate3loader/scripts/capture.py` the window capture. See
`docs/execution-trace.md` for what the sessions measured.

## How it hooks in

The game reads the pad through exactly one call site of `__imp__XamInputGetState`. The SDK
implementation lives in `librexruntime.so`, so a definition in the executable takes over
every guest call and forwards to the real one through `dlsym(RTLD_NEXT)` — the same
approach as the `audio_dump_path` tap. After the real input system fills the state, the
harness overwrites player one's gamepad with the script's current step.

The hook does integer work only. It runs on a guest thread inside a guest call, where
floating-point exceptions are unmasked — the lesson from the capture tap's SIGFPE, in
`docs/shadow-harness.md`. Everything else (starting the script, markers, frames, the bail
log) happens on a controller thread.

**Pad polls are not frames: this build polls about 600 times a second** (1,196 polls in the
first 2,000 ms). Script durations are milliseconds, so they do not depend on that rate.

## Script format

```
<duration_ms> [a b x y lb rb l3 r3 start back up down left right] [lx= ly= rx= ry= lt= rt=]
@mark NAME       log a marker when the timeline reaches it
@capture NAME    log a marker and save the guest output frame
# comment
```

Sticks are -100..100 with up and right positive; triggers 0..100. A step holds exactly that
pad state for its duration, and anything it does not name is neutral. The script starts
`skate3_input_script_settle_ms` after gameplay is first reached.

`probe/trace/check_script.py SCRIPT` validates a script and prints its marker timeline
before a session is spent on a typo.

| cvar | default | |
|---|---|---|
| `skate3_input_script` | empty | absolute path to the timeline |
| `skate3_input_script_settle_ms` | 3000 | wait after gameplay before starting |
| `skate3_input_capture_dir` | empty | where `@capture` writes PPM frames |
| `skate3_input_capture_every_ms` | 0 | also capture this often while running |

## Knowing what the game did, not what was asked for

**Bails come from the game's own decision.** `PhysicalPlayerHiLOD::IsWipeoutRequested`
(`sub_82DB9100`) returns nonzero when the game puts a skater down. Board state cannot see a
bail, because the skater ends up back on the board — that is `sk8-engine-linux`'s finding,
and it cost two builds there with a signal that could never fire. The function is polled per
player several times a frame and stays true across a fall, so true polls within 1.5 s of the
previous one count as the same bail. In the first scripted session: 2 true polls out of
24,952, one bail.

### The counter is not filtered to the local skater

`IsWipeoutRequested` is polled **per physical player**, and the worlds here are populated.
The counter therefore reports anyone going down, including a pedestrian next to the skater,
which is how a bail got attributed to an X press that did not cause one. `sk8-engine-linux`
flagged exactly this: its own consumer filters on the local skater's animation interface and
its note says the signal "needs a local-player filter before it is correct".

Until the harness records which player each wipeout belongs to — the object pointer arrives
in `r3` — **treat the count as "someone fell", not "the skater bailed", and confirm every
bail against a frame.**

**Frames.** `@capture` reads the presenter's guest output and writes a PPM;
`probe/trace/frames_to_png.sh DIR [WIDTH]` converts a directory to PNG. In parallel,
`run_play.sh` runs `skate3loader`'s `capture.py` against the game window every couple of
seconds — the game draws through GTK, and with `GDK_BACKEND=x11` it is an X11 client whose
pixels can be read. The first session produced 15 in-process frames and 62 window shots, 59
of them distinct, so neither path hit the all-black capture failure recorded in the
`skate3` project's notes. The in-process frames are current, not stale: a frame and the
window shot taken in the same wall-clock second show the same thing.

**The two capture clocks do not share an origin.** A window shot's name counts seconds from
when `capture.py` started, which is after the game process appears — 10 s after launch in
one session — while script time starts 3 s after gameplay is reached. Mapping one onto the
other by assuming a shared start put the frames 6 s out and briefly looked like the
in-process capture was showing something else entirely. Use the files' mtimes against the
log's timestamps instead.

## What the controls did

Measured in the first scripted session, from frames and the bail counter:

| input | intent | result |
|---|---|---|
| `a` taps | push | **works** — the skater crossed the plaza and reached a different area |
| `back` | open the replay editor | **works** — timeline, transport controls and the A/B prompts are on screen |
| `y` | (guessed: bail) | **steps off the board** — frames show the skater walking down the stairs on foot |
| right stick down then up | ollie | not separable from the frames taken |
| `lb` + `up` | session-marker reset | **no visible effect** — the view is identical before and after |
| late flip, `lb`+`rb`+`y`, `x`, double flick, full-speed collision | bail on demand | **none demonstrated** — see below |

Two sessions, eleven attempts, two wipeout events, and **not one of them is attributable to
an input**. The second session's single bail landed during the pushes rather than in any
attempt window, and its frame does show the local skater mid-fall. The third session spaced
each attempt about eight seconds apart, so the log could name the marker a bail followed —
it named `A3_x` — but the frames refute it: at that instant the local skater is riding
upright while a pedestrian stumbles beside him.

So the script still cannot bail on demand, and the remaining question is not timing.

## Running a session

```sh
probe/trace/run_play.sh LABEL SCRIPT [EVERY_S] [FOR_S]
probe/trace/summarize_play.sh LABEL
```

`run_play.sh` launches the traced game with the script, finds its pid, starts the window
capture series, and refuses to start while any `skate3` is running. `summarize_play.sh`
prints the markers, bails, poll rate, trace dump and corpus coverage, and converts frames.

**Other sessions on this machine run the same binary.** `out/build/linux-release` is a
symlink to `linux-release-jammy`, and at least one other project's launcher runs
`linux-release/skate3`, so a rebuild here changes their binary too. Coordinate before
relinking, and never kill `skate3` by name — match your own process by its log path.

## Files

| file | what |
|---|---|
| `recomp/src/skate3_input_script.cpp` | the harness: input override, script engine, bail counter, frame capture |
| `probe/trace/scripts/*.txt` | timelines |
| `probe/trace/check_script.py` | validate a timeline offline |
| `probe/trace/run_play.sh` | one session, with the window capture series |
| `probe/trace/summarize_play.sh` | results in one command |
| `probe/trace/frames_to_png.sh` | PPM frames to PNG |
