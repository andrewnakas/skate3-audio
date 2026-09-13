# sub_82F4DED0 -- the image's sine

A scalar leaf: f1 in, sin(f1) out in f1. |x| is divided by pi and rounded to n; the remainder is
taken against pi in two parts (Cody-Waite), fed through an odd Taylor polynomial to x^19 in Horner
form, and negated when n is odd. The input's sign is restored by an fsel on the original f1. A
magnitude at or past 2.2e8 returns the NaN at 0x82FB58C8, and +/-0 returns the input unchanged.

Outside the 216 audio-thread functions only because the executed-set attribution is by FIRST call:
it is first called on load_thread. It runs on the audio thread too, through the spatial panner and
the per-channel filter stages, and it is the reason those four Rust ports could not be replayed.

Gates: 1 pass (leaf), 2 pass (no stores but the red zone), 3 pass (no timebase), 4 pass (f1 named).
Constants measured from the image dump and listed in the port header; all read live.
