# 0009 — The rip chain is configuration; the comment it produces is a plan value

**Status**: accepted

## Context

A tagged FLAC that outlives its manifest should still say where it came from:
which pressing, and what the record was played and digitised through. Players
show the COMMENT tag, so that is where it has to land.

Neither half of that fitted anywhere. `metadata` had no `comment` field, and it
had no `disc_number` either — the plan could say a track was `C1` but not that it
was on the second record of a set, so a double album tagged as sixteen tracks of
one disc.

The equipment is the awkward half. It is not a per-record decision: the same
turntable, cartridge, phono stage and ADC serve every album until something is
replaced, and retyping the chain into every plan is how it ends up wrong in one
of them. That argues for configuration. But configuration is read by planning
skills only — `tests/contracts/test_layer_boundaries.py` stops `executor.py`
importing `config` at all — and it is the executor that writes tags.

Two shapes were available. Give `RipChain` a method that renders itself into a
sentence and have the tagger, or the executor, call it. Or keep the equipment in
configuration, let the skill compose the sentence, and put the finished string in
the plan.

The first is shorter and wrong. What belongs in a comment, in what order, under
what wording, and whether the pressing's catalogue number joins it — those are
choices. A `summary()` in `config.py` is a choice encoded in Python, made once
for every record anyone ever processes, and invisible in the plan that is
supposed to be the complete account of what was done. It would also have made the
executor's tags depend on a file the executor is forbidden to read.

## Decision

Three optional fields on `MetadataPlan`: `comment`, `disc_number`, `total_discs`.
All default to `None`, so a 3.0 plan still validates and still executes to the
same bytes; `SCHEMA_VERSION` goes to 3.1 as an additive change.

A new top-level `[rip]` configuration section — turntable, tonearm, headshell,
cartridge, stylus, phono stage, ADC, software, notes — sibling to `[analyzer.*]`
and `[preferences]` rather than folded into preferences, because it records
equipment rather than taste. Every field is optional: a chain nobody wrote down
is better described by omission than by a guess. `RipChain` deliberately has **no
method that renders it**. `plan-metadata` reads the section, composes the
sentence, and writes it into `metadata.comment`; the executor writes what the
plan says and never learns where the words came from.

`[rip]` is excluded from `Config.digest()`, which covers what can change a
measurement. Renaming a cartridge must not invalidate an analysis.

The tagger writes `DISCNUMBER` / `DISCTOTAL` and `COMMENT` as Vorbis comments,
and `TPOS` and `COMM` for ID3. Both needed handling outside the plain frame map:
`TPOS` packs `n/m` into one frame where Vorbis uses two keys, and `COMM` carries
a language and a description that Vorbis has nowhere to put.

## Consequences

The plan stays the complete record: read it and you know exactly what the comment
tag will say, without also holding the configuration that produced it. Two people
with different rigs get different comments from the same skill and the same
release, which is the point.

Nothing validates the chain. If the ADC in the file is wrong, it is wrong in
every tag written after it, silently — there is no measurement to check it
against, and inventing one (guessing the interface from the sample rate) would be
a worse kind of wrong. It is a field the person maintains.

`disc_number` is about the disc, not the side. The two sides of one record are
one disc — the side is already in `tracks[].position` — so a double album is
discs 1 and 2 across four plans, not four discs.
