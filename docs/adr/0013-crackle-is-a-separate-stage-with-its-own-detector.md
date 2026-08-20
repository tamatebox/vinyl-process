# 0013 — Crackle is a separate stage with its own detector

**Status**: accepted

## Context

A listener reported crackle rather than discrete clicks, and the reflex was to
lower `declick.threshold`. That is the wrong lever, and the reason is in the tool
that ships both controls separately. The ClickRepair 3.9 manual:

> "The detection/repair algorithms used for click removal are not particularly
> attuned to the removal of very short (1–3 sample), rapidly repeated, small
> clicks, which are usually heard as 'crackle' or 'buzz' (not 'hiss')."

Its DeCrackle is "a post process which examines **every sample individually** and
adjusts those which are sufficiently out of line", against click removal's "more
**collective** decision making process, making it likely that small clicks could
be overlooked when they are closely spaced".

`block_ratio` is the collective kind: it asks whether a *segment* is an outlier
against its 40 ms neighbourhood. That is the right question for an impulse of a
few hundred microseconds and the wrong one for a bed of one-to-three sample
events — each a weak outlier, and there are thousands. A threshold low enough to
catch them starts interpolating the music long before it clears the bed.

## Decision

`decrackle` is its own stage, its own plan section and its own algorithm.

**The detector is `curvature_ratio`**: a sample's `|second difference|` against
the mean `|second difference|` of its own neighbourhood. Two properties are
inherited from `block_ratio` deliberately — it is a **ratio**, so a quiet passage
and a loud one are judged alike, and it is **local**, so the answer does not
depend on how much audio the function was handed
([0010](0010-the-click-statistic-is-local.md)). The algorithm id names the
detector, the same convention `declick` follows.

Three consequences are part of the decision, not side effects:

- **Runs after `declick`, before `split`.** Discrete defects before continuous
  ones ([0012](0012-the-executor-has-a-pre-split-phase.md)), which is also what
  keeps the two from fighting: the wide events are already bridged, so this
  stage's per-sample statistic is not looking at their edges.
- **Events wider than `max_event_width_samples` (default 3) are dropped, not
  repaired.** At that width the event is a click and `declick` owns it. The stage
  therefore cannot bridge anything the click detector would have found.
- **`threshold` has no default**, for `declick`'s reason. It is a curvature
  ratio, so *smaller* is more aggressive — the opposite direction from
  ClickRepair's sensitivity slider, which is "an arbitrary percentage". Only that
  tool's **repair-rate band** transfers: 1 in 200 samples is "suspicious", 1 in
  1000–2000 the typical floor.

**The executor reports the repair rate in the manifest.** Each repair stage's
`detail` carries `repaired N of M samples (1 in K)`, computed by comparing the
buffers it already holds. That figure is the only calibrated quantity either
repair stage has, and it used to be obtainable only by diffing two rendered
directories — which meant it was usually not obtained, and a `declick` setting an
order of magnitude below the band was chosen twice on one record without anyone
noticing.

### Native only

`ffmpeg` does **not** get this capability, despite the project's usual preference
for delegating. It has no crackle filter. Mapping `decrackle` onto `adeclick`
with a narrow window was considered and rejected: `adeclick` is impulsive-noise
removal, which is the collective family the citation above says is *not* attuned
to crackle, so the mapping would contradict the very reference that justifies the
stage. An engine implements only what it has.

## Consequences

- `SCHEMA_VERSION` 3.3 → **3.4**, minor: the section is optional and disabled by
  default, so a 3.3 plan validates unchanged and executes to the same bytes.
  Archived plans at 3.1 and 3.2 still `lint` clean and still `verify` bit-identical.
- **Bright material masks quiet crackle**, and the stage under-repairs there. High-
  frequency programme content raises the denominator of the ratio: measured on
  synthesised material, a 3.1 kHz tone at −22 dBFS carries a curvature comparable
  to a crackle event 40 dB below the programme, and detections across the same
  injected bed fell by more than half against the same bed under a bass line. The
  failure direction is the safe one — fewer interpolations where they would be most
  audible — but it means **a threshold does not transfer between passages of one
  side**, and a bed genuinely below the material's own curvature is not reachable
  at any threshold. `plan-decrackle` says so, and a test pins it.
- `linear` is the default interpolator, not `ar`. Across one to three samples a
  straight line between the two survivors cannot leave the range they span, so it
  cannot diverge on any material, while an AR fit would be estimating a model from
  a context far larger than the hole it fills.
- `lint` gains `decrackle-without-threshold` (error),
  `decrackle-width-is-clicks`, `decrackle-without-declick` and
  `decrackle-with-pitch-protection` — the last because the manual warns that pitch
  protection together with de-crackling "may seriously impair de-crackling", and
  `declick.params.confirm_k` is this engine's nearest equivalent.
- The stopping condition is **this project's judgement, not the manual's**. The
  band is cited; "past it, the pressing is beyond the tool" is not, and the source
  hedges its own 1-in-200 line with "although it might lead to results that are
  more acceptable". `plan-decrackle` marks it as ours.
