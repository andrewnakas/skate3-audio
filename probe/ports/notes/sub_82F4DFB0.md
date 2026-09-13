# sub_82F4DFB0 -- the image's cosine

A scalar leaf: f1 in, cos(f1) out in f1. It shifts |x| by pi/2, divides by pi and rounds to n, then
reduces against pi in two parts with the quotient offset by one half, so the sine's odd polynomial
serves unchanged. It reads the same table as sub_82F4DED0 and differs in three places: the pi/2
shift, the half offset, and an exact early return of 1.0 when |x| is zero. The range test is on
|x| + pi/2 rather than on |x|.

Outside the 216 audio-thread functions only because attribution is by first call: it is first
called on Main XThread. It runs on the audio thread through the spatial panner and the filter
stages.

Gates: 1 pass (leaf), 2 pass (no stores but the red zone), 3 pass (no timebase), 4 pass (f1 named).
