# Which verified bodies should run by default

The sweep left 138 native bodies proved equal to the original, all of them behind
`--skate3_audio_native=true`. Making any of them the default is a **different judgement** from
proving them equal, and this document settles it with the evidence rather than by preference.

## What promotion actually changes

Under the shadow harness a native body runs on a rewound copy of memory and its result is
discarded; the game keeps the original's answer. Promotion removes that safety net: the native
body's stores are the game's stores.

So the question is not "was this body correct on the calls we compared" — it was, at zero
divergence, or it would not be verified. The question is **how much of the body those calls
exercised**. Nothing in the harness measures path coverage, so any answer here is an argument
from proxies, and the proxies should be stated rather than hidden behind a round number.

## The evidence, measured

Per-function comparable calls come from the two final all-armed shadow sessions, `f1_boot` and
`f2_play`. Taking the **weaker** of the two profiles per function, because a function exercised
heavily in one and barely in the other has only been seen in one situation:

| | |
|---|---|
| verified ports | 138 |
| compared in **both** profiles | 137 |
| compared in one profile only | 1 |
| declined any call (`skipped > 0`) | 1 |
| median comparable calls (stronger profile) | 61,886 |
| ran natively in a promoted session, no crash | 138 |

The promoted session is real evidence and also limited evidence: all 138 bodies ran for real,
audio held 187.5 frames a second dead on real time with zero silent submits, and nothing crashed.
That says the set is *viable*, not that every path in it is right.

## The criterion

**Promote a verified body when its weaker profile compared at least one call per lifted line, and
at least 100 calls.**

Calls per line rather than a flat count, because a flat threshold treats an 18-line predicate and
a 742-line frame builder as the same risk. Scaling with the body's size is still a proxy — lines
are not branches — but it is a proxy that moves in the right direction, and it is the difference
between the two candidate cuts:

| criterion | promote | hold |
|---|---|---|
| calls/line >= 1 and >= 100 calls | **124** | 14 |
| flat: >= 1,000 calls | 114 | 24 |
| calls/line >= 10 | 113 | 25 |

The flat cut holds back ten bodies that ran tens of thousands of times simply for being small,
and the strict ratio holds back eleven more for no reason the evidence supports.

## The 14 held back, and why each

Weaker profile, stronger profile, lifted lines:

| function | weaker | stronger | lines | why it is held |
|---|---|---|---|---|
| `sub_82B305C0` | 0 | 100,810 | 269 | never compared at all in one profile |
| `sub_82B427D8` | 4 | 4 | 742 | the largest body in the set, seen four times |
| `sub_82B2F2C8` | 4 | 4 | 433 | as above, at 433 lines |
| `sub_82B2F798` | 4 | 4 | 178 | four calls |
| `sub_82B2FEA8` | 4 | 4 | 138 | four calls |
| `sub_82B2FE00` | 4 | 4 | 113 | four calls, and this is the body whose misread constant caused the project's first divergence |
| `sub_82B20E18` | 1 | 1 | 143 | one call, in each profile |
| `sub_82B1DC00` | 5 | 8 | 115 | a handful |
| `sub_82B370E8` | 23 | 10,112 | 477 | 477 lines against 23 calls in the weaker profile |
| `sub_82B373C8` | 23 | 10,112 | 451 | as above |
| `sub_82B376B8` | 23 | 10,112 | 171 | as above |
| `sub_82B43D78` | 23 | 257 | 163 | thin in both |
| `sub_828E2D78` | 20 | 45 | 81 | thin in both |
| `sub_82B3D578` | 10 | 11 | 18 | small, but seen ten times |

These are **not** suspect bodies. They diverged nowhere. They are bodies whose evidence does not
yet carry the weight promotion puts on it, and the way to promote them is to get them called more
— a profile that exercises whatever they are for — not to argue the threshold down.

## How the decision is expressed

`kPortVerifiedThin` is a status that shadows like a verified port but is never promoted, because
`PortPromoted` tests `== kPortVerified` exactly. The 14 carry it. This is the same shape as
`kPortPartial`, which exists so a path-split port cannot be promoted on the strength of a path it
never compared.

What is **not** done here: the `skate3_audio_native` cvar still defaults to false, so today
nothing runs natively unless asked. Flipping that default is a one-line change and a decision
about the recomp's behaviour rather than about this evidence, so it is left to its owner. When it
is flipped, 124 bodies become the game's own audio code and 14 stay behind the flag.
