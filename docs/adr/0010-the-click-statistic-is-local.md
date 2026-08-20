# 0010 — The click detector's statistic is local

**Status**: accepted

## Context

The first click detector thresholded a **robust sigma** — a median-absolute-deviation
estimate of the input's own spread — and called a sample damaged when its curvature
exceeded some multiple of that sigma. One sigma per input is one number for the
whole buffer, and that is the flaw: it is not a local statistic.

Three consequences were measured on real audio, without injecting any damage:

- **The answer moved with the buffer.** Handed the same 60 s in different chunk
  sizes, the robust-sigma detector's count moved by up to **7.8x**; an energy ratio
  over two local windows held to within 10 %. Because the analyzer sees a whole
  side and the engine sees one track, the two halves of this project were
  describing different events — measured once at **38 693** clicks reported
  against **58 355** spans repaired.
- **It over-detected and missed at the same time.** On a near-clean pressing used
  as a negative control it claimed **1082 events a minute** while finding *none* in
  the inter-track gaps — the one place the surface is unmasked and a detection is
  therefore positive evidence. A detector that finds nothing where the damage is
  visible and thousands of things under the music is following the music.
- **It under-detected in quiet passages**, for the same reason in reverse: a
  global spread is dominated by the loud material, so a click in a quiet stretch
  never clears it.

None of this is a tuning problem. A single global figure cannot be made local.

## Decision

`block_ratio` replaced it: **the mean-square of a click-width window divided by
the mean-square of its own 40 ms neighbourhood**, computed after a zero-phase
high-pass. It is the statistic Audacity's click detector is built on, and it has
both properties the sigma lacked — it is a *ratio*, so the absolute level of the
passage does not enter, and both windows are local, so how much audio surrounds
them does not either.

Three things follow, and are deliberate:

- **The algorithm id names the detector**, not the interpolator, because the
  detector is the half with evidence behind it. Which interpolator reconstructs
  best is unsettled and stays a `params` choice.
- **`threshold` has no default and cannot get one.** It is a ratio of energies, and
  no ratio suits two pressings — on one album the two *sides* wanted different
  rungs. The analyzer reports the whole ladder (`clicks.threshold_sweep`) as the
  fact and the engine refuses to run without a value, so the choice is explicit
  rather than hidden. See `plan-declick`.
- **The analyzer and the engine share the arithmetic** through `signal_ops.py`, so
  the statistics a skill reasons about and the events the engine repairs are the
  same events by construction, without the two layers importing each other.

## Consequences

- A threshold is per recording and per side. Nothing in the codebase may supply
  one, and reaching for a remembered value is the failure this record exists to
  name.
- The sweep is cheap: the high-pass, the two running means and the curvature are
  all independent of the threshold, so a whole ladder costs barely more than one
  point. That is why reporting the ladder was affordable at all.
- A robust sigma still appears inside the detector, but only to *localise* an
  event's span once the ratio has flagged it (`curvature_sigma` in
  `signal_ops.py`). Detection and localisation are different jobs; a global
  statistic is adequate for the second.
- `block_ratio` still fires on some percussive attacks. That is the residual cost
  of the ratio, reported per rung as `onset_coincidence` rather than papered over,
  and separating surface from programme more reliably would be a new algorithm id.
