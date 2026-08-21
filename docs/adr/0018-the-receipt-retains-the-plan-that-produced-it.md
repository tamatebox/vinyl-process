# 0018 — The receipt retains the plan that produced it

**Status**: accepted

## Context

`manifest.json` is the receipt, and it records the plan as a `DocumentRef`: a
path and a SHA-256. Both halves fail in the same way over time. The path is
relative to whatever directory ran `execute`, so it stops resolving as soon as
anything moves. The digest is one-way, so it can prove that a plan on disk is
*not* the one that ran and can never say what the one that ran contained.

Everything a stage was parameterised with therefore lives in exactly one place —
the plan file — and nothing keeps that file next to the render it produced. The
manifest's per-stage `params_digest` does not close the gap: it is a digest too.

What that has cost this archive, on one pressing:

```
declick      params_digest=f4d8a80f1fce  detail=algorithm=block_ratio
declick-r10  params_digest=885a129408cb  detail=algorithm=block_ratio
declick-r20  params_digest=5294b19c79d2  detail=algorithm=block_ratio
declick-r35  params_digest=9a8fa828dd5a  detail=algorithm=block_ratio
```

Four declick thresholds were rendered, compared by ear and one was chosen. Four
distinct digests prove four distinct parameter sets ran. The thresholds are
recoverable from none of it. The plans happened to survive in a scratch directory
outside the archive, which is luck rather than design and is not how it read from
the manifest.

That matters beyond convenience. The project ranks its evidence — a published
standard's test vectors, then documented practice, then **a measurement on a real
transfer**, then synthesis — and `declick`'s and `decrackle`'s thresholds have
nothing above the bottom rank. A record of which threshold was actually chosen on
which pressing, and what the repair rate came out at, is the only route to the
third. Losing it is losing the calibration, not just the paperwork.

The same gap made `verify` report the wrong failure. Given a plan file that had
been edited since the render, it re-executed *that* plan and printed
`differs: 04 - ….flac` — which reads as lost determinism. Four review renders in
this archive fail that way, and diagnosing one took considerably longer than it
should have because the message named the wrong cause.

## Decision

**`execute` writes a copy of the plan beside the manifest.** The name is derived
from the manifest's, so two sides or two rungs of a review ladder never collide:
`manifest.json` → `manifest.plan.json`, `manifest-side-a.json` →
`manifest-side-a.plan.json`.

The copy is **byte-identical** to the plan file whenever there was one, so its own
SHA-256 equals `manifest.plan.sha256` and the pairing is checkable rather than
assumed. Where the plan came from memory rather than a file — a programmatic call,
a test — the model is serialised instead; the digest will not match, and the
parameters are still what mattered.

**`verify` prefers that copy** and checks the digest of whatever plan it loads
against `manifest.plan.sha256` before re-executing. On a mismatch it exits 66
saying the plan on disk is not the one that ran — edited since, or never kept —
and does not run. A lost plan and lost determinism are different failures and must
read as different failures.

This is deliberately **not** a schema change. Embedding the plan inside
`manifest.json` was considered: it would make the receipt self-contained, which is
strictly stronger. It was rejected for now because the manifest is a description
of what happened and the plan is a description of what was asked for; folding one
into the other duplicates every field and makes the receipt grow with the plan.
The copy keeps the two documents' purposes separate while putting them in the same
place, and it needs no version bump, so archived plans at 3.1 and 3.2 are
unaffected.

## Consequences

- Every `execute` writes one extra small JSON file. No audio bytes change, no
  schema version moves, and `run_key` is unaffected: re-executing a real plan
  produced the same `run_key` and the same output digest as before, and the
  retained copy is byte-identical to the plan file it came from.
- **The archive is not a regression check for this, and cannot be.** No record in
  it was processed by the current version — the newest plans are at schema 3.2,
  from before five stages existed and before `declick` moved ahead of `split`. Two
  of its `split/` manifests used to `verify` green and now report a plan mismatch,
  because the plan file has been edited since the render and the old check compared
  only the *output*: they were passing on outputs that happened to match a plan
  that no longer existed. The stricter check turns a false green into a stated
  reason, which is the point; it does not make those renders reproducible, and
  nothing will.
- **Retention is mechanical; the history is not.** The copy preserves the
  parameters and the manifest preserves the outcome, including the repair rate.
  Neither can record which rung a listener chose, or what was wrong with the ones
  rejected — that is a checkpoint answer, and it exists only in the conversation
  where the checkpoint happened. A ledger of records processed therefore belongs
  to the skill layer, not to a Python report generator, which could only ever emit
  the columns above. Nothing is built for it yet; the retention is the half that
  had to exist first, because a skill cannot recover a file that was overwritten.
- **A render made before a stage moved still will not reproduce, and should not.**
  `declick` ran after `split` until
  [0012](0012-the-executor-has-a-pre-split-phase.md), so a pre-0012 manifest with
  declick enabled differs by design; the fades used to be applied before repair and
  biased the detector. `manifest.stages[]` carries the order, which is how a
  receipt's era is read. This decision makes the *plan* recoverable, not the old
  executor.
- The recorded audio path has the same relativity problem as the plan path, and
  `verify` now falls back to looking beside the manifest. That is a papercut fix
  rather than a guarantee: a path recorded relative to a directory nobody kept is
  still a path nobody can resolve.
