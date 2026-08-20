# 0004 — Track titles live only in the metadata section

**Status**: accepted

## Context

Export filenames are built from track titles, and tags contain the same titles.
An earlier draft of the contract put a `title` on each `split.tracks[]` entry *and*
in `metadata.tracks[]`, with the skills instructed to keep them in agreement.
Instructions like that are how two sources of truth are born.

## Decision

`split.tracks[]` carries positions only. `metadata.tracks[]` is the single source
of truth for titles, and `metadata/naming.py` renders filenames from it.

`metadata.enabled: false` means "do not write tags"; the names are still used, and
a track with no title falls back to `Track 07`.

## Consequences

- Filenames and tags cannot disagree.
- A missing title is a lint warning rather than a silent inconsistency.
- `plan-split` and `plan-metadata` have genuinely disjoint outputs, which is what
  makes them independently replaceable.
