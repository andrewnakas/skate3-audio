# sub_82F4DE80

Leaf, 34 lines, no stores, no callees: `floor(double)`. Argument f1 (double), result f1.
Called 2,219,605 times in the boot profile on `RwAudioCore Dac` -- the hottest port so far.

Algorithm, instruction for instruction: `fctidz`/`fcfid` gives trunc(x); `fsel` on (x - trunc)
steps down by the pool constant at `0x82010108` when the fraction is negative; `fsel` on
(pool constant at `0x820514D8` - |x|) passes large magnitudes through as already integral;
`fsel` on -|x| passes +/-0 through with its sign (NaN also falls to the else side of every
`fsel`, so NaN comes out via the f0 chain, which returns x itself).

Stores: none. Reads: the two 8-byte pool constants (`lfd f13,264(r11)`, `lfd f0,5336(r10)`),
declared with `spec.read`. Window: empty; `Windows()` always returns true.

Result mask: `kReturnF1`. All 16 call sites (TUs 11, 38, 100, 101, 104) execute `frsp fN,f1`
or use f1 directly right after the `bl`; the scratch f0/f10-f13/r10/r11 are not reproduced.

Gates: 1 pass (leaf), 2 pass (no writes), 3 pass (no timebase), 4 pass (f1 named).

Unsure: the two pool values are not verified from the image -- by shape they are 1.0 and 2^52,
but the body loads them so the port is correct either way. `fctidz` edge handling copies the
lifted line verbatim (NaN, > 2^63, cvttsd2si indefinite); those inputs are unlikely on this
path and would only be exercised if a caller ever passes them.
