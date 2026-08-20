# 0002 — Positions in contracts are integer samples

**Status**: accepted

## Context

Track boundaries can be expressed in seconds or in samples. Seconds read better;
samples cut better. A boundary stored as `123.456` seconds turns into a different
sample index depending on rounding, and the whole point of the plan is that two
runs produce identical bytes.

## Decision

Every position in every contract is an integer sample index into the source file:
`start_sample`, `end_sample`, `lead_in_end_sample`, `positions_sample`,
`peak_sample`. Durations in seconds appear only as redundant, human-readable
companions (`duration_seconds`), never as the authority.

Millisecond quantities that describe a *process* rather than a position stay in
milliseconds, because that is how the operator thinks about them: `fade_in_ms`,
`max_click_width_ms`.

## Consequences

- Cuts are exact and reproducible; no rounding policy has to be agreed on.
- Skills must convert durations from a tracklist into samples themselves, using
  `source.sample_rate` from the analysis. The `plan-split` skill says so
  explicitly.
- A plan is tied to a sample rate. Resampling happens at export, after the cuts,
  so it cannot invalidate them.
