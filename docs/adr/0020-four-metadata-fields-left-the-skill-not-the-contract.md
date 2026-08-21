# 0020 — Four metadata fields left the skill, not the contract

**Status**: accepted

## Context

`MetadataPlan` carries `genre`, `styles` and `label`, and `TrackTag` carries
`position` — the vinyl side and number as printed on the label, `"A1"`, `"B3"`.
All four are optional with defaults (`null`, `[]`, `null`, `null`), and a `null`
field is simply not written: no `TCON`, no `TPUB`, and no `TXXX`/`VINYL_POSITION`.

`plan-metadata` used to resolve all four from the release and fill them. It also
carried the citations that existed to support them, and a paragraph on where the
`"A1"` form comes from.

Both albums that reached that checkpoint struck all four. That is two for two, and
it is also the entire sample — no album has ever kept them. Two is not much, but
it is the whole of the evidence in either direction, and the cost of being wrong is
asymmetric: filling a field the person does not want makes them say no again on
every record, while leaving it out costs a request the one time somebody wants it.
The skill already recorded the first occurrence in its own "a resolved field is not
a wanted field" paragraph, and recording it there did not stop the second.

The obvious smaller change was tried first and is not enough. Flipping the default
— resolve them, offer them, fill only on a yes — leaves all four named in the
skill's prose and shown in its `## Output` example, so a later run has everything
it needs to reinstate them, and the paragraph explaining that they are offer-only
is one more thing for a reader to weigh rather than a thing they cannot do. The
planner is the only enforcement there is: nothing in the codebase checks which
optional fields a plan chooses to fill.

## Decision

**The four fields are removed from `plan-metadata` entirely** — from the
procedure, from the `## Output` example, from the checkpoint's tag table, and from
the two entries in `## Outside references` that existed only to support them. The
skill no longer mentions them, so it cannot prescribe them.

**The contract keeps them, and this is deliberately not a schema change.** They
are optional with defaults, so every archived plan that fills them stays valid and
still tags exactly as it did; `metadata/tagger.py` is untouched and still writes
all four when a plan carries them. What changed is which plans carry them.
Removing them from the model would be a breaking major bump that invalidated
archived plans in order to express a preference, which is the wrong layer for it:
a plan is a record of decisions, and "we do not tag genre" is a decision, not a
contract.

`catalog_number` was kept, and the asymmetry is the point rather than an
oversight: it identifies the pressing rather than describing it, and it is
available to the filename template.

## Consequences

- **A plan can still carry all four and nothing rejects it.** Someone who wants a
  genre tag hand-edits the plan or asks for it, and the skill now gives no guidance
  on the form and no citation for it. That is the accepted cost.
- **One thing worth not losing went with the removed paragraph**, so it is recorded
  here. The `"A1"` / `"B3"` form was cited from Discogs' own API response —
  `tracklist[].position`, which `scripts/discogs_release.py` returns — and
  explicitly *not* from the database guideline that mandates it, because that
  guideline lives on `support.discogs.com`, which answers a plain fetch with 403
  and has therefore never been read in this repository. Anyone reinstating the
  field should cite the API response, not the guideline. ID3v2.4 has no frame for a
  vinyl position, which is why the tagger writes a user-defined `TXXX` under the
  description `VINYL_POSITION` and why nothing standard reads it.
- **The likely way this gets undone is a diff, not an argument.** Someone compares
  the skill against `schemas/processing_plan.schema.json`, finds four contract
  fields the skill never mentions, and reads the silence as the skill being out of
  date. This record is the answer to that reading. No test can carry the point:
  `tests/contracts/test_skills.py` checks frontmatter, headings, a URL in
  `## Outside references`, the line ceiling, relative links and the `lint` mapping,
  and nothing compares a skill's prose against the fields of the section it owns.
  Nothing should — a test that pretended to would be gamed or disabled
  ([0017](0017-a-skill-is-authored-against-a-rule-file.md)).
- **If this should ever be configurable rather than fixed, `[preferences]` is the
  right home** — tag-set selection is taste, and taste is read by planning skills
  only. Nothing is built for it, and building it now would be speculative while the
  answer is the same for every record. Reach for it the first time two records want
  different tag sets; until then, deleting the prose is the cheaper answer and this
  record is why.
- The removal reduced what the checkpoint has to present, which is the second-order
  benefit and worth naming: the tag table is now short enough to read, and the four
  fields were the bulk of what made it long.
