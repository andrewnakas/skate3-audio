# Running the recomp for audio work (macOS)

## Build

The SDK submodules' `.git` entries were renamed to `.git.orphaned-2026-09-07` and their
histories deleted; only the source trees survive. CMake only tests that `.git` exists, so
restoring the names is enough to configure. Re-cloning is not an option worth taking —
the histories are gigabytes and the disk is ~94% full.

```sh
cd skate3recomp-dev/third_party/rexglue-sdk/thirdparty
for d in */.git.orphaned-2026-09-07; do mv "$d" "$(dirname "$d")/.git"; done

cd /Users/nakas/skate3/skate3recomp-dev
cmake --preset macos-fast
/Users/nakas/skate3/polite_build.sh out/build/macos-fast rexglue 3   # ~5 min
/Users/nakas/skate3/polite_build.sh out/build/macos-fast skate3  3   # ~5 min
```

`generated/` is already populated and fresh, so `generate-all` is not needed unless the
codegen TOML changes. Building `rexglue` first compiles most of the SDK, which is why the
game build is then short. Always use `polite_build.sh`: it suspends compilation when free
memory drops below ~700 MB and whenever `skate3` is running — on this 8 GB M1 a build and
a play session cannot coexist.

## Launching — the title update must be staged

**This is the part that is easy to get wrong.** `skate3_install_tu` is documented as
"empty to ask". Launched without it, the game shows an installer overlay, the main guest
thread blocks in `NtWaitForSingleObjectEx` while holding critical section `830B9088`, and
the render thread piles up `RtlEnterCriticalSection: waiting 5s…128s` warnings. The audio
transport keeps running and reports **100% all-silent submits with zero XMA voices** —
which looks exactly like a total audio failure and is not one. Pass the package:

```sh
cd skate3recomp-dev/out/build/macos-fast
./skate3 --game_data_root=/Users/nakas/skate3/game \
         --skate3_install_tu=/Users/nakas/skate3/TU_12K2276_000000C000000.00000000000O3 \
         --log_file=/tmp/s3_audio.log --log_level=info \
         --audio_stats=true --xma_stats=true \
         --audio_dump_path=/tmp/guestmix.raw --audio_dump_max_frames=4000 \
         --fullscreen=false --window_width=960 --window_height=540 --vsync=false
```

There is no headless mode — it needs a real surface. Keep the window unoccluded; when it
is covered, `presentation suspended: window flags … occluded` appears and presentation
stalls.

## Baseline, 2026-09-11 (first audio measurement ever taken on this machine)

`audio_stats` and `xma_stats` had never been enabled in any macOS run before this.

```
SDLAudioDriver: device freq=48000Hz channels=6 sample_frames=512 (10.7ms);
                guest 48000Hz/6ch/256 -> pushing 6ch, fold=device
Audio stats (5.0s): callbacks=469 frames=938 (187.5/s, real-time=187.5/s)
                    silence_chunks=0 queue_depth=5..8 max_callback_gap=11ms
Guest mix  (5.0s): submits=926 all-silent=7 (0.8%) gaps=1
XMA stats  (5.0s): frames=1407 (281/s) blocks=9380 active_ctx=8
                   REAL voices=3 decode_cpu=0.4% of one core
```

Error counts over the whole run: `exceeds buffer size` **0**, `Frame sizing incorrent`
**0**, `invalid or unregistered` **0**, `RtlEnterCriticalSection: waiting` **0**, codec
tag table repairs **0**.

Conclusions:

- **Bug 4 is already fixed.** The `XmaContext … input offset 16416 exceeds buffer size
  16384` flood in the August logs is gone. `xma_old_fix_input_overrun` and
  `xma_old_fix_split_detection` became default-true after those logs were recorded, and
  they hold. Chasing it would have been chasing a ghost.
- **Bugs 1–3 do not reproduce on macOS.** They are the out-of-order-ARM64 handheld cases;
  the mitigations are in place and nothing trips them here. Reproducing them will need
  either the mitigations disabled or an Android/iOS device.
- **`fold=device`.** The device reports 6 channels and the 5.1→stereo fold is left to
  CoreAudio, the route the `audio_device_channels` cvar text calls untested. On a stereo
  laptop this is worth comparing against `--audio_device_channels=2`, which takes the
  engine's own downmix.

## Reference capture

`out/reference/guestmix_baseline.raw` — 24,576,000 bytes = 4000 frames × 256 samples ×
6 channels × 4 bytes, **big-endian float32, planar**, tapped at the guest mixer submit
before any fold. This is the ground truth the Rust port gets compared against.
