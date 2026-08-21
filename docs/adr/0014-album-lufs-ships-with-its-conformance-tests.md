# 0014 — `album_lufs` ships with its conformance tests

**Status**: accepted

## Context

`docs/architecture.md` listed "No loudness (LUFS) normalization" as a known
limitation and stated the terms on which it could be lifted:

> `album_gated_rms` has BS.1770-4's block geometry, its two gates and
> ReplayGain's album pooling, so it measures the programme rather than the
> silence — but no K-weighting, which is what separates a level in dBFS from
> loudness in LUFS. `album_lufs` would be that filter plus conformance tests
> against the EBU Tech 3341 vectors, and is deliberately absent until both exist.

That position was taken because an unverified loudness implementation is worse
than none: it produces a number in the right units that people will act on. Two
things made it a small addition rather than a large one — the gating machinery,
the block geometry and the album pooling were already in place, and both the
standard and the compliance tests are public.

Three things had to be settled before it could ship.

**The filter coefficients are published for 48 kHz only.** BS.1770 Tables 1 and 2
give them for that rate and then say: "Implementations at other sampling rates
will require different coefficient values, which should be chosen to provide the
same frequency response that the specified filter provides at 48 kHz." It does not
say how, and this project's transfers are 44.1, 48 and 96 kHz.

**The compliance signals are described, not supplied.** EBU Tech 3341's Table 1
specifies each test case as a signal description — "Stereo sine wave, 1000 Hz,
−23.0 dBFS (per-channel peak level); signal applied in phase to both channels
simultaneous; 20 s duration" → `I = −23.0 ±0.1 LUFS`. That matters here, because
this repository commits no audio files.

**LUFS is a different quantity from `album_gated_rms`, not a better one.**

## Decision

`album_lufs` is a `normalize` mode. No stage, no pipeline work, no plan section:
the block geometry, both gates and the album pooling already existed, and the
addition is the K-weighting plus the channel-weighted sum and the −0.691 offset of
BS.1770 equation (2).

**The coefficients are derived, and the derivation is held to the published
table.** `signal_ops` carries the analogue prototype (f0, gain, Q per stage) and
re-derives the biquads per sample rate through the bilinear transform. The
justification is not that the prototype is the standard's — it is that at 48 kHz
the derivation reproduces every tabulated coefficient of Tables 1 and 2 **to
machine precision**, largest discrepancy 9e-16, and a test asserts it. That test is
the whole warrant for using the filter at 44.1 or 96 kHz, and it is what stops the
constants being numbers someone recalled.

The warping is not free. The Recommendation's own reference reading — "a 0 dB FS,
1 kHz (997 Hz to be exact) sine wave applied to the left, centre, or right channel
input, the indicated loudness will equal −3.01 LKFS" — comes out at −3.0075 at
44.1 kHz, −3.0103 at 48 kHz and −3.0276 at 96 kHz. Inside Tech 3341's ±0.1 LU, and
a real difference, which is why the conformance cases run at more than one rate.

**The conformance tests synthesise Tech 3341's signals.** Cases 1–6 all pass at
44.1 and 48 kHz, worst error 0.024 LU against a ±0.1 LU tolerance. Which cases
are covered is itself part of the decision:

| Cases | Status |
|---|---|
| 1, 2 | Covered. Pin the channel **sum** and its linearity — averaging the channels instead of summing would read −26 on case 1 |
| 3, 4 | Covered. Case 3 can only pass with the *relative* gate, case 4 needs the absolute one |
| 5 | Covered, and the sharpest: quiet segments only 6 dB down, so a gate placed a decibel off fails it |
| 6 | Covered. The **only** case that can catch a wrong channel weight, since in stereo every weight is 1.0. A vinyl transfer is never 5.0 — the multichannel rows of the weight table exist so this case is runnable |
| 7, 8 | **Not covered.** They need "authentic programme" audio that cannot be synthesised, and this repository commits no audio files |
| 9–14 | **Not applicable.** They test momentary and short-term *meters*. There is no meter here — one integrated figure per album — so they describe a device this project does not implement |

**It is a separate mode, on `adr/0008`'s reasoning applied again.** Putting
K-weighting inside `album_gated_rms` would change what an existing plan means: the
same `mode` and `target_db` would produce a different gain, and a plan is supposed
to be a complete record of a decision. `album_gated_rms` keeps its exact
behaviour, and the two now differ by exactly the K-weighting's verdict on the
material's spectrum — a test pins that they do, in both directions.

## Consequences

- `SCHEMA_VERSION` 3.4 → **3.5**, minor and additive: a new value of
  `normalize.mode`, and `analysis.peaks.lufs` as an optional field. An older plan
  names an older mode and produces the same gain; an older analysis omits the
  field.
- **`analysis.peaks.lufs` exists so the skill has a measured reference.** Without
  it `plan-normalize` would be choosing a LUFS target with nothing measured to
  place it against, which is the uncalibrated-dial failure this project keeps
  running into. It is measured over the whole recording, so it includes the
  lead-in and the run-out that the cuts discard — the executor re-measures on the
  split audio, and the skill has to say which figure it is quoting.
- `album_lufs` is a **level** target, so it needs `peak_ceiling_db` for
  `adr/0007`'s reason. `lint`'s `rms-without-peak-ceiling` now covers it, and a
  new `lufs-target-is-loud` warns above −9 LUFS — that line is this project's, not
  a cited one.
- `target_db` on this mode is **in LUFS, not dBFS**. The contract's `le=0.0` bound
  still holds, and the field name does not change: a fifth mode does not earn a
  fifth field, and the mode id already says which quantity is meant.
- What is still absent: a momentary or short-term meter, and `peaks.lufs`'s
  per-track equivalent. Neither is needed to normalize an album.
