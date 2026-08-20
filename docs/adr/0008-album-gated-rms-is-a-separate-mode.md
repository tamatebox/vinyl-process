# 0008 — Gated RMS is a new mode, not a fix to `album_rms`

**Status**: accepted

## Context

`album_rms` averaged the squares of every sample the plan cut, inter-track gaps,
fades and all. `plan-normalize` offers the mode for matching loudness across a
collection, and an ungated average cannot do that: silence drags the measurement
down, so a side with long gaps measures quiet and normalizes loud. Two pressings
of the same programme, one with wide gaps, end up at audibly different levels.

This is a solved problem. ITU-R BS.1770-4 measures over 400 ms blocks at 75 %
overlap and applies two gates — an absolute one at −70 that drops silence, and a
relative one 10 dB under the mean of what survives that drops the quiet tail.
ReplayGain's album gain pools every track's blocks before gating, so the album is
measured as one continuous piece of programme.

The obvious move was to put the gates inside `album_rms`. That would change what
an existing plan means: the same `mode` and `target_db` would produce a different
gain, and a plan is supposed to be a complete record of a decision.

## Decision

`album_gated_rms` is a new mode. `album_rms` keeps its exact behaviour and its
place in the contract, the way `track_peak` does — present, honest about what it
measures, and steered away from by the skill and by `lint`'s `ungated-rms` and
`rms-without-peak-ceiling` findings.

The gates, the block geometry and the pooling rule are BS.1770-4's and
ReplayGain's; they are constants of the named algorithm, not choices, so they live
in `signal_ops.py` and not in the plan. Choosing the mode is the decision.

K-weighting is deliberately *not* applied. That would make the figure loudness in
LUFS, and a LUFS implementation nobody has checked against the EBU Tech 3341 test
vectors is worse than no LUFS at all. `album_gated_rms` is a level in dBFS
measured over the programme, and says so.

## Consequences

- Old plans keep producing bit-identical albums; the mode id is the version.
- `analysis.peaks.gated_rms_db` reports the same measurement over the whole
  recording, so a skill can predict the gain before executing.
- Channels are averaged rather than summed, unlike BS.1770, so the value is
  directly comparable with `peaks.rms_db` on the same material.
- A real `album_lufs` mode remains open, and is now a small addition: the gating
  machinery is in place and only the K-weighting filter and its conformance tests
  are missing.
