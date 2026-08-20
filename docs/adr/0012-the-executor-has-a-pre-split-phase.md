# 0012 — The executor has a pre-split phase

**Status**: accepted

## Context

The executor's order was `split → declick → normalize → resample → export`.
Splitting first looks natural — everything after it is per track — but it puts
two things beyond reach, and both are properties of the ordering rather than of
any pressing.

**A noise profile has nowhere to come from.** It must be taken from the medium's
own unmodulated groove: the lead-in, the run-out, or an inter-track gap, because
a profile taken from a quiet *musical* passage models the music too. Practice is
explicit — Audacity's LP workflow takes the print "from either the lead-in grooves
immediately before the music starts, or from a lead-in between tracks", and Sound
Forge's guide requires that "the noise print must contain only the steady unwanted
bed". `plan-split` discards all three **by rule, on every record**: the lead-in
and run-out to keep the stylus drop out of `album_peak`, and the dead middle of
every gap because it belongs to neither track. So no stage after `split` can ever
see one.

**Repair works on ramped, truncated material.** `native.split()` applies the
fades the plan asked for, so `declick` saw audio that had already been shaped. The
energy ratio is invariant to a constant scale but not to a ramp across its 40 ms
context window: a fade makes one side of the window louder than the other, which
lowers the ratio and biases the detector *towards missing* clicks — in the head
and tail margins, which are bare surface and therefore where a record's clicks are
densest. The same window was also truncated at every track edge. Practice repairs
before shaping anything: the reference workflow is DC offset (step 7), subsonic
filter (step 8), clicks (step 9), and only then track labels (step 11).

Both are fixed by the same change, and neither is fixable without it.

## Decision

**The executor has two phases.** Before the cuts, on the whole side:
`prefilter → declick`. After them, per track:
`split → normalize → resample → export → tag`.

`declick` moved. Its position is now part of what a plan means, which is why this
is a record and not a refactor.

### Schema strategy — the load-bearing part

New sections are **optional, with a disabled default**, so `SCHEMA_VERSION` takes
a **minor** bump: 3.2 → 3.3.

Making them required would force a *major* bump, and `check_major_version` has
consumers refuse a foreign major — which would make every archived plan
non-re-executable at a stroke. Re-execution is this project's central promise, so
it wins over the "all five sections are always present" convention that
`docs/architecture.md` states for the original five. Those five stay required;
the newer ones are optional and disabled. The convention is therefore no longer
uniform, and the doc is amended to say so rather than quietly drifting.

The first section on the new rail is **`prefilter`**, owning both DC blocking and
the subsonic high-pass, with one `plan-prefilter` skill. Two one-line filters do
not each justify a stage and a checkpoint, but both are genuine
preservation-versus-listening choices rather than constants, so they are a plan
section and not a compiled-in default.

## Consequences

- **Nothing archived changes.** All ten plans across the five job directories have
  `declick.enabled = false`, at schema 3.1 and 3.2 both, and a disabled stage
  produces identical output wherever it sits. So the reorder costs nothing in
  reproducibility *today*. It stops being free the first time a plan enables
  declick, and that is precisely what this record is for: a 3.1 plan with declick
  enabled, re-executed under 3.3, would produce different bytes than it did.
  Nothing in the file would say so, which is why the position is documented here
  rather than inferred from the code.
- `declick` now processes lead-in, run-out and gap material that the cuts discard.
  Harmless to the audio, wasted arithmetic, and it removes the fade bias — which
  was the point.
- The manifest gains a `prefilter` stage record and its `StageName` literal is
  reordered into pipeline order. `vinyl-process verify` compares output digests
  only, so an added stage record does not affect it.
- De-noise and de-crackle are now *possible* rather than blocked. A `denoise`
  section can carry its noise-profile region as source sample indices, chosen by a
  skill from `silence.regions`, and the executor can extract the profile before
  cutting. That is not built here; what changed is that the pipeline's shape no
  longer forbids it.
- `docs/architecture.md`'s "no subsonic filter and no DC blocking" limitation is
  resolved, and its "the fades run before `declick`" limitation is resolved. Its
  "de-noise cannot be a post-split stage" limitation is narrowed to "not yet
  built".
- A subsonic filter arguably belongs upstream in `vinyl-archive`, and adding it
  here does not settle that. It improves the listening copy, it is reversible per
  plan, and the capture keeps what it removes.
