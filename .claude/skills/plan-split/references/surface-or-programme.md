# Reading `band_profile` and `periodicity`

Supporting reference for [SKILL.md](../SKILL.md)'s *Surface or programme?*. Read
it when a boundary is actually in doubt; the routing table in the skill says
which of the two instruments answers which question.

## `band_profile` — finding an entrance

Surface noise piles its energy into one band — on a played LP usually the
lowest, because unequalised groove noise rises about 3 dB/octave and RIAA
playback then boosts the bass and cuts the treble — and *that* band sets the
broadband level. On one 12" a clean run-out fell monotonically from -71 dBFS in
40-150 Hz to -93 dBFS in 3-8 kHz. So an intro sitting 20-30 dB above the surface
in 400-3000 Hz moves `rms_profile` by a fraction of a dB, which is why `silence`
misses it. Per band, in one 0.2 s frame:

- the entrance is a **step in a band with its neighbours unmoved** — measured
  once as the 400-1000 and 1000-3000 Hz bands up 14-19 dB in a single frame while
  the two bands below them did not budge. Crackle cannot make that shape: it is
  broadband, so it lifts several bands at once.
- compare a band against **its own `floor_db`**, never another band's, and treat
  `floor_db` as a percentile of the whole file rather than as the level of
  silence — on a side that is mostly music it *is* a music level, so read steps
  between frames, not absolute headroom.
- a **single frame** that lifts one band is a tick, not an entrance. Require the
  lift to persist.
- the tilt still tells you *which kind* of surface you are looking at — falling
  towards the top means smooth groove noise, a lifted top band means abrasion —
  but never whether the stretch is programme.

## `periodicity` — settling a tail

A groove defect repeats once per revolution — 1.8 s at 33 1/3 rpm, 1.333 s at
45 — and never on the beat. For a window in `periodicity.windows[]`:

- compare each `revolution[].r` against the window's own `peaks[0].r`. Where a
  revolution correlation rivals the top peak, the window is the pressing.
- otherwise check that `peaks[0].period_seconds` is `programme_period_seconds` or
  a simple multiple or division of it, and that its prominence above
  `baseline_r` is in the region of `programme_peak_prominence`.
- where nothing correlates strongly — every `r` small, whatever the level — there
  is no music there either. Silence and damage both look like this.

Expect the beat to show *more* strongly in a quiet passage than in the loud body
of the same track — the surface stops masking it. A faint stretch that locks to
the grid harder than the track does is still that track.

## Two readings that look sound and are not

`baseline_r` **is not** a surface marker: on the same side the crackling lead-in
sat at 0.17-0.23 while the run-out, whose tick is far cleaner, sat at -0.03, and
quiet programme reached 0.24. Subtract it, do not threshold on it.

A single correlation taken at `programme_period_seconds` is not a discriminator
either: on a second side the whole-programme estimate landed on the bar while
individual windows expressed the sub-beat, and the comparison separated nothing.

## Where the numbers come from

Nothing here is outside practice; the citations for this skill are in
[SKILL.md](../SKILL.md)'s *Outside references*. Two claims above are in-house and
uncalibrated: that unequalised groove noise **rises about 3 dB/octave**, and the
**14-19 dB** step that marked an entrance. Both are one 12"'s measurement or an
unsourced rule of thumb, so read them as the shape to look for and not as a
threshold to apply.

## `run_out` — the trailing edge, measured rather than read

`run_out.start_sample` is this whole question already answered for the one
boundary where it comes up every time: where the last track ends. It is the two
instruments above combined — `periodicity` supplies an **anchor**, the last window
whose own top autocorrelation peak still beats the platter's revolution
correlations, and `band_profile` refines that anchor forward to the first frame at
which every band has arrived at the run-out's own level.

**Evidence: one record, four sides.** On it the pair landed within 0.6 s of the
answer derived by hand, against 5.0-9.3 s early for
`boundaries.lead_out_start_sample` and up to 27 s late for
`silence.regions[-1].music_end_sample` — the latter because that region held the
run-out *and* the needle lift, and its reference is the region's minimum, which
the lift owns. That is one record. It is a better starting point than either
marker and it is not a settled figure, so check it as *SKILL.md* step 5 says: read
`periodicity` past your own cut and prefer the longer of the two answers when they
disagree.

Two things it cannot do, both structural rather than provisional:

- **the anchor is a 12 s window on a 4 s hop**, so without the band refinement the
  answer is only that coarse. Where `band_profile` is absent the section reports
  nothing rather than the anchor alone.
- **it has no outside citation.** Trimming the run-out is standard practice and is
  cited in the skill; locating it by correlating against the revolution period is
  this repository's own construction, inherited from `periodicity`, which was
  itself built in-house. The phenomenon behind it — a groove defect struck once per
  turn — is common knowledge; using it as a boundary detector is not what the
  field's tools do, and they detect track breaks from level with a person
  adjusting them.
