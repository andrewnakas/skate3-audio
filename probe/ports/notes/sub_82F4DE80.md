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

Measured 2026-09-13, replacing an unverified guess: the two pool values are **1.0 and 1e18**
(`0x43ABC16D674EC800`), read out of the image. The note used to say "by shape they are 1.0 and
2^52", which was wrong and unmeasured. 1e18 is the better constant for the job -- the largest
round decimal magnitude below 2^63, which is the bound `fctidz` needs. The port is unaffected
either way, because the body loads the cells live rather than folding them in. `fctidz` edge handling copies the
lifted line verbatim (NaN, > 2^63, cvttsd2si indefinite); those inputs are unlikely on this
path and would only be exercised if a caller ever passes them.
