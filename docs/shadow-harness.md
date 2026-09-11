# Shadow harness and guest-mix capture: Phase 1, measured

**Phase 1's exit criterion is met, 2026-09-11.**

- **(a)** `EVENT_SUBMIT` ran **1,678 times under the shadow harness with zero register and
  zero memory divergence**, then was promoted and ran natively at least 1,024 times from
  boot to gameplay.
- **(b)** A 4,000-submit `audio_dump_path` capture passes a signal-level layout check, and
  `tools/mixdiff.py` reads it.

Code lives on recomp branch `audio/phase1-harness`, commit `e581969`, with drop-in copies
in `recomp/src/`. Sessions run through `probe/harness/`.

## Running a session

```sh
probe/harness/run_session.sh LABEL [MACRO]     # -> probe/harness/out/LABEL.log, LABEL.guestmix.raw
python3 probe/harness/check_capture.py probe/harness/out/LABEL.guestmix.raw
```

| env | default | effect |
|---|---|---|
| `SHADOW` | `true` | `--skate3_audio_shadow` |
| `NATIVE` | `false` | `--skate3_audio_native`; shadow wins when both are on |
| `PLAY_MOVIES` | `true` | `--skate3_demo_path_play_movies` — see the next section |
| `AUDIO_DUMP_FRAMES` | `4000` | `--audio_dump_max_frames`, 21.3 s |
| `GDB_SCRIPT` | unset | run under gdb; `crash.gdb` stops on SIGFPE and prints the backtrace |

The game ignores SIGTERM. End a session with `pkill -KILL -x skate3`; the capture is
flushed per submit, so it keeps whole records.

## `EVENT_SUBMIT` only runs while a movie plays

In the Phase 0a trace `EVENT_SUBMIT` never ran. The first caller of the PacketPlayer
command producer (`sub_82B28A00`) was the `MoviePlayer2` thread, issuing selector 1, and
the demo path force-completes every frontend movie under boot automation.
`skate3_demo_path_play_movies`, added to the recomp's demo path and off by default, lets
them play. With it on, `EVENT_SUBMIT` runs about 1,700 times across the boot movies and not
again during gameplay.

So **anything on the PacketPlayer path needs a session with movie playback** before it can
be shadow-verified. The producer has no direct call sites in the generated code — it is
reached through a function pointer — so reading the code will not say which other paths
reach it.

## What the harness needed before it could pass a correct function

| | as drafted on macOS | now | why |
|---|---|---|---|
| registers | `memcmp` of the whole `PPCContext` | only what the ABI obliges a callee to preserve — `r1`, `r2`, `r13`–`r31`, `f14`–`f31`, `v14`–`v31`, `v64`–`v127`, `cr2`–`cr4` — plus the return registers the hook names | the lifted `EVENT_SUBMIT` leaves scratch in `r9`–`r11` and `cr6`; a correct native body never reproduces those, so the old compare flagged **every** call |
| memory | one window, ≤ 64 KB | a list of windows, 64 KB in total | `EVENT_SUBMIT` writes four places; the old window covered two of them |
| evidence | a log line on divergence only | milestone counts plus a reporter thread every 10 s | a clean session has to leave positive evidence, and a function that stops being called still needs its final count logged |

The preserved ranges come from the save/restore helpers the image actually uses
(`__savegprlr_14..31`, `__savefpr_14..31`, `__savevmx_14..31` and `__savevmx_64..127`), not
from a generic PowerPC ABI table.

`EVENT_SUBMIT`'s windows are the FIFO head and tail (`player+0x148`, 8 bytes), the new
packet's next pointer (`packet+0x0C`), and — when the list was non-empty on entry — the old
tail's next pointer.

### What the harness cannot verify at all

The native body runs a **second time**, against rewound memory. That is safe for a function
whose effects are memory this harness can rewind — and unsound for one that calls out to
guest code with effects it cannot.

`EVENT_STOP` (`sub_82B28C18`) is the first case: when a decoder is live it calls
`sub_82B3C930`, whose four indirect calls release and unregister the voice. Replaying that
against a rewound copy would tear down an already-released object, and no memory window can
undo a release. So the hook compares only calls that arrive with no decoder, runs the
original for the rest, and counts them (`g_event_stop_unverifiable`). A count that never
drops to a small fraction means the function is mostly unverified, whatever the divergence
figure says.

The same test applies to every later candidate: **before writing a native version, check
what it calls.** A leaf, or one calling only pure-memory helpers like `memset`, is fully
comparable; anything that allocates, frees, releases, signals or submits is comparable only
on the paths that avoid those calls. That is a property of the function, not a shortcoming
to be engineered around — and a promoted native body still has to perform those calls for
real, so the promoted path carries risk the shadow run never covered.

Still true of the harness: windows must cover every byte a function writes, because a write
outside them keeps the lifted value while the native body runs. `lr`, `ctr`, `xer`, `fpscr`,
`msr` and the reservation state are not compared. Another thread writing a watched window
during the rewind would read as a divergence; not seen so far.

## The capture tap

The guest mixer's output reaches the host through one import. `sub_82F10980` copies the
mixer's interleaved buffer into a planar stack buffer (`r1+1888`, which is why every session
logs the same first-submit address, `0x7006E730`) and passes it to
`XAudioSubmitRenderDriverFrame`. The host driver only `memcpy`s it.

The SDK lives in `librexruntime.so`, so defining `__imp__XAudioSubmitRenderDriverFrame` in
the executable takes over every guest call site. The tap copies the frame, then forwards to
the runtime's own implementation through `dlsym(RTLD_NEXT)`. No SDK change was needed.

`mixdiff.py` assumes the layout, so reading a file back only shows the file is readable.
`check_capture.py` tests the layout from the signal instead:

| session | mode | silent submits | peak | roughness planar / interleaved | seam ratio |
|---|---|---|---|---|---|
| `p1_movies` | shadow | 1,822 | 0.6602 | 0.122 / 0.529 | 0.71 |
| `p1_fixed` | shadow | 1,825 | 0.6602 | 0.124 / 0.536 | 0.63 |
| `p1_native` | native | 1,824 | 0.6602 | 0.135 / 0.522 | 1.57 |

All 4,000 submits, 0 non-finite samples in each. Read as planar, the audio is roughly four
times smoother than read as interleaved. Steps across submit boundaries look like steps
inside a submit, so no submit was dropped or reordered. `mixdiff.py` reads `p1_movies` and
`p1_fixed` back as EXACT.

## SIGFPE: host float work inside a guest call

The first version of the tap killed the game at exactly the 4,000th submit. Under gdb, with
the cap moved to 2,000, it died at the 2,000th instead:

```
Thread "Audio Worker" received signal SIGFPE
#0  CloseLocked(char const*)                 divsd (%r15,%rcx,1),%xmm1
#1  __imp__XAudioSubmitRenderDriverFrame
#2  sub_82F10980
#3  rex::runtime::FunctionDispatcher::Execute
#5  rex::audio::AudioSystem::WorkerThreadMain
```

The fixed tap logs the control word it finds on entry: **MXCSR `0x0000`** — every FP
exception unmasked. The division of `submits × 256 / 48000.0` was inexact, and trapped.

The SDK already knows about this. `AudioSystem::WorkerThreadMain` re-masks after the guest
callback returns, with a comment that "the FPSCR emulation leaks MXCSR state". Hooks run
**inside** that callback and get no such protection. `0x0000` is exactly what
`disableFlushModeUnconditional()` writes from a zero `fpu_csr`, and every initialisation path
sets the mask bits, so the worker thread's guest FPSCR state was most likely never
initialised. That last part is inference; the fault site and the control word are measured.

**Rule:** host-only float work in a hook masks exceptions around itself and restores the
guest's control word on exit (`FloatExceptionsMasked` in `skate3_audio_dump.cpp`). Native
DSP replacements are different: their float work *is* the guest's, and has to run under the
guest's own mode.

## Captures are not reproducible run to run

Three sessions booted the same way, aligned at their first non-silent submit:

| pair | first audio | identical aligned submits | first difference |
|---|---|---|---|
| `p1_fixed` vs `p1_movies` (both native off) | 1162 / 1162 | 2,054 of 2,838 | submit 49 |
| `p1_fixed` vs `p1_native` | 1162 / 1174 | 2,196 of 2,826 | submit 253 |
| `p1_movies` vs `p1_native` | 1162 / 1174 | 2,040 of 2,826 | submit 49 |

Between the two native-off sessions, the first differences are tiny: 1e-15 to 1e-19, against
0.0 or other tiny values. Those are normal floats, not denormals, so this is not a
flush-to-zero difference. Later differences are full scale: 435,869 differing samples are at
least 1e-3. At the one submit tested, a whole-channel shift of up to ±48 samples does not
explain them. **The cause is not established.**

Two consequences:

1. **Cross-session captures cannot verify promotion.** The native-on session falls inside the
   band between two native-off sessions. That is consistent with promotion changing nothing,
   and proves nothing more. The shadow harness is what proves `EVENT_SUBMIT`.
2. **PLAN Phases 4 and 6 assume reproducibility the recomp does not have.** Both want a
   capture that "matches bit-for-bit" for the same scene or trigger. Before that criterion
   means anything, either the source of the nondeterminism has to be found — thread timing,
   random variation, streaming — or the comparison has to happen within a single process.

## Build costs, measured

| change | cost |
|---|---|
| `CMakeLists.txt` | reconfigure plus 261 build steps, mostly SDL3's C files |
| a harness source file | 1–3 compiles plus relink, 3–4 s |
| `generated/skate3_init.h` (the trace hook) | 127 objects, 195 s — `docs/environment-linux.md` |

## Files

| file | what |
|---|---|
| `recomp/src/skate3_audio_shadow.{h,cpp}` | the harness |
| `recomp/src/skate3_audio_native.cpp` | `EVENT_SUBMIT`, three modes |
| `recomp/src/skate3_audio_dump.cpp` | the `audio_dump_path` tap |
| `recomp/src/skate3_audio_probe.cpp` | XMA feed probe, unchanged |
| `probe/harness/run_session.sh` | one session |
| `probe/harness/check_capture.py` | layout check from the signal |
| `probe/harness/crash.gdb` | stop on SIGFPE with a backtrace |

The recomp's demo-path change (`skate3_demo_path_play_movies`) lives only in the recomp,
because it is not an audio file.
