# 0005 — Dither is seeded from the plan

**Status**: accepted

## Context

Reducing 24-bit captures to 16 bit without dither produces correlated
quantisation distortion. Dither is the correct fix, and dither is noise — which
collides head-on with "same audio plus same plan gives the same bytes".

## Decision

`export.dither` selects the type (`none` or `tpdf`) and `export.dither_seed`
selects the noise instance. The generator is numpy's PCG64 via
`np.random.default_rng(seed)`, whose bit stream is stable across numpy versions.

## Consequences

- A dithered export is still bit-reproducible, and `verify` still works.
- Changing the seed deliberately re-rolls the noise and changes every digest; the
  `plan-export` skill is told to leave it alone unless that is the intent.
- Nothing else in the codebase may use randomness. Any new random process must
  take its seed from the plan the same way.
