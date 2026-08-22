# 0023 — What this produces is a listening master

**Status**: accepted

## Context

`architecture.md` opened by saying this pipeline "produces a processed, split,
tagged album fit for listening **and long-term archival**". Read as one object
serving both purposes, that sentence is wrong in a way that costs level, and it
did.

On a 1971 Japanese pressing the level decision was researched properly and came
out backwards. The searches found two schools and both were quoted accurately:

- **The archival school.** IASA requires transfers "carried out without subjective
  signal alterations", with enhancement "only on a copy of the unmodified archival
  transfer"; the Grammy Museum's preservation methodology has masters "preserved
  flat (unprocessed), without any audio manipulation, dynamics, equalization".
- **The needledrop school.** Normalise across all sides with one gain rather than
  per file, "because the mastering engineer expects you to experience every master
  release as a WHOLE"; VinylStudio offers exactly that as "adjust all sides by the
  same amount (which will be governed by the loudest album side)".

The first school was applied, `normalize` went off, and the album shipped 2.99 dB
below where its own headroom allowed. The owner then said it was too quiet, which
it was.

The error was not the citation. It was the object the citation was about. **The
preservation master here is the raw capture**, produced by `vinyl-archive` and read
by this pipeline, which never writes to it — so "no subjective signal alterations"
is satisfied before any plan exists, by the shape of the tool rather than by a
decision. `album/` is downstream of that: it is the copy, and both schools permit
the copy to be processed. The Grammy Museum document says so in the same
paragraph — "Organizations can provide listening copies that have been 'cleaned
up,' but these should be noted as such and stored as access audio."

An archival rule applied to a derived listening copy is not caution. It is a
category error that looks like caution, which is what made it survive a
checkpoint: the reasoning was cited, the arithmetic was right, the alternatives
were measured and rejected on sourced grounds, and the conclusion was still wrong
by 3 dB.

## Decision

`album/` is a **listening master**. State it in `CLAUDE.md` as an operating
principle, and correct the scope sentence in `architecture.md` so the two do not
disagree.

Consequences that follow, and are the reason this is a record rather than a
comment:

- **Preservation-master citations do not bear on any stage decision.** They are
  satisfied by the raw capture. A skill that reaches for one is reasoning about the
  wrong file.
- **`normalize` off is a level decision like any other**, to be argued from the
  headroom available and from needledrop practice — not the safe default that needs
  no argument.
- **The needledrop school is the applicable one for level**: one gain across all
  sides, governed by the loudest side. The contract cannot express that directly —
  one plan is one side and there is no shared-gain mode — so it is reached by
  back-solving `target_db` per side to a common gain, and the rationale has to say
  that is what the two numbers encode. That workaround is a known limitation with
  its own entry in `architecture.md`, not a licence to normalise per side.
- **Every deliverable question is a listening question.** Depth, dither and rate
  still follow the capture, because widening or resampling a copy adds nothing — the
  arguments there are `plan-export`'s and are unaffected.

## Consequences

The record was re-planned and re-exported with one album-wide gain of +2.99 dB
across both sides, `verify` green on both, and the raw capture untouched as before.

What this does not change: the raw capture remains the thing to keep, and it is the
only object in the job directory that no plan may modify. If someone genuinely
wants a flat, unprocessed rendering of a side, that is the capture — not a
`normalize`-disabled run of the executor, which is a listening master that happens
to have been left quiet.

Nothing enforces this. It is a premise, which is why it is written in `CLAUDE.md`
where it loads every session rather than left for the next person to re-derive from
two schools of citation that both sound authoritative.
