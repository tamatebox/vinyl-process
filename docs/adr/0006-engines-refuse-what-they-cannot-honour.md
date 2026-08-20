# 0006 — Engines refuse parameters they cannot honour

**Status**: accepted

## Context

Engines are interchangeable but not equivalent. The plan's `declick` section has a
`strength` knob; ffmpeg's `adeclick` filter has no equivalent. The engine could
ignore the value, approximate it, or fail.

Ignoring it is the dangerous option: the plan would claim a 60 % repair, the
manifest would look clean, and the audio would be a 100 % repair. The plan would
have stopped being a record of what happened.

## Decision

An engine converts canonical plan parameters into its own units when the mapping
is deterministic and documented — that is part of its contract, not a decision.
When there is no honest mapping, the engine raises and the run stops.

Concretely: `ffmpeg` maps `threshold` to `adeclick:t` and `max_click_width_ms` to a
clamped analysis window (both documented in `docs/dsp-engines.md`), and refuses any
`strength` below 1.0.

## Consequences

- A plan that cannot be executed faithfully fails loudly, at the start.
- Engine documentation is part of the contract: each engine states how it
  interprets `threshold` and what it does not support.
- `vinyl-process lint` catches the structural half of this (missing engine, missing
  capability) before any audio is touched; the parameter half surfaces at
  execution.
- Consequence for skills: a threshold is not portable between engines, and
  `plan-declick` says so.
