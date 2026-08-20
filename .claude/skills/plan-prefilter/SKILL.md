---
name: plan-prefilter
description: Choose DC blocking and the subsonic high-pass cutoff applied to the whole side before the cuts. Produces the prefilter section of processing_plan.json. Use when planning removal of DC offset or warp rumble from a vinyl recording.
---

# Plan Prefilter

Decide what below the music reaches the listening copy. Two switches, one
section, applied to the whole side before `split`: **DC blocking** and a
**subsonic high-pass**.

The default answer is **no** to both. This is the one stage whose `enabled` is
`false` in the contract, because removing something a transfer captured is a
decision and the archival answer is often to remove nothing. Ask; do not carry a
default through.

## Outside references

Where a number below is a matter of LP-transfer practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it.

**The filter, and its numbers.** Audacity's
[Sample workflow for LP digitization](https://manual.audacityteam.org/man/sample_workflow_for_lp_digitization.html)
step 8, "Reduce subsonic rumble and low frequency noise":

> "Use Effect > High Pass Filter with a setting of **24 dB per octave** roll-off,
> and a cutoff frequency of **20 - 30 Hz** to reduce unwanted subsonic frequencies
> **which can cause clicks when editing**."

Three things come from that quote and nothing else does. The **rolloff** (24
dB/octave, which is why `highpass_rolloff_db_per_octave` defaults to 24 and is
stated in dB/octave rather than as a filter order). The **band** (20-30 Hz;
`lint` reports `subsonic-cutoff-outside-band` outside it and warns
`subsonic-cutoff-high` above 40 Hz, where the filter is taking musical bass).
And the **reason**, which is worth reading twice: the cited purpose is not that
rumble sounds bad — it is that subsonic energy *causes clicks when editing*. That
is a processing argument, not a listening one, and it is the honest case for this
stage.

**Both halves, and the order between them.** The same workflow separates them and
runs them in the order this stage does: step **7** is "Remove DC offset", step
**8** is the high-pass, step **9** is "Remove clicks and pops". So DC first, then
subsonic, then repair — which is exactly the executor's pre-split phase followed
by `declick`. The engine applies the two in that order for a mechanical reason as
well: a DC offset is a step at the filter's input and an IIR high-pass answers a
step with a settling transient, so removing the mean first leaves it nothing to
settle from.

**What this stage does *not* have a citation for** is being worth running at all
on a given record. No source found says "filter when rumble exceeds X". So the
decision below rests on a measurement plus the person's answer, and the
`rationale` must say which.

**Not a de-rumble, and not upstream.** `docs/architecture.md` argues a subsonic
filter "belongs upstream in `vinyl-archive` at least as much as here", and adding
it here does not settle that
([adr/0012](../../../docs/adr/0012-the-executor-has-a-pre-split-phase.md)). What
this stage is: reversible per plan, and an improvement to the listening copy. What
it is not: a fix for a warped record or a misaligned turntable. Where
`spectral.rumble_db` is high, say so as a fact about the equipment or the
pressing — that belongs upstream, and filtering here hides it from the next
person.

## Inputs

**Uncalibrated numbers in this skill**: the **−30 dB** `spectral.rumble_db` above
which this stage is worth *raising*, and the **0.001** (−60 dBFS) DC offset above
which `dc_block` is worth raising. Both in-house triage thresholds for *when to
ask*, not for what to do. The band and the rolloff are cited; these are not.

From `analysis.json`:

- `spectral.rumble_db` — the energy below 40 Hz **relative to the whole
  recording**, as 20·log10 of an amplitude ratio, so it is ≤ 0 and is **not** a
  level in dBFS. Compare it with the other entries of `spectral.bands`, which are
  computed the same way, and never with `peaks.peak_db`. −48 dB is negligible;
  −20 dB is a tenth of the amplitude, so 1 % of the energy, in a band nobody can
  hear.
- `recording_info.dc_offset` — per channel, in linear amplitude. A non-zero value
  shifts the waveform toward one rail, so one side of it clips early and the peak
  a peak mode normalizes against is inflated by exactly the offset.
- `peaks.peak_db` and `peaks.true_peak_db` — what the headroom claim below is
  measured against.
- `spectral.bands` — read the lowest band against its neighbours, so a genuinely
  rumbly transfer can be told from one whose whole spectrum is bass-heavy.

Either section can be absent if its analyzer failed (`analyzers[]` says so). With
neither `spectral` nor `recording_info`, you have no reason to enable this stage:
re-run `analyze --analyzers spectral,recording_info` or leave it off and say why.

## Decision guide

1. **Default**: `"enabled": false`. Say in one line that nothing below the music
   was removed, and move on. This is the right answer on a clean transfer.
2. **`dc_block: true`** when `recording_info.dc_offset` is materially non-zero on
   either channel (above ~0.001, i.e. −60 dBFS). It is exact and has no
   transition band, so it costs nothing audible — but it still changes bytes, so
   it is still a decision.
3. **`highpass_hz`** from the cited band: **20** where the intent is to touch as
   little as possible, **30** where warp rumble is the reason. Nothing here
   defaults it; `null` means no subsonic filter, and that is a different plan from
   `enabled: false` with a `dc_block`.
4. **Raise it at all** when `spectral.rumble_db` is high — above about −30 dB is
   where it is worth a checkpoint — or when the offset in 2 is present. Below
   that, filtering is removing something nobody can hear and nothing measured
   complains about.
5. **Leave `highpass_rolloff_db_per_octave` at 24.** It is the cited figure. A
   different value is a departure from the only calibration this stage has, so
   name a reason.
6. **Never set a cutoff to fix something else.** A rumbly-sounding pressing, a
   clipped transfer and a mis-tracking stylus all look like low-frequency
   trouble, and none is repaired by a high-pass.

## Output

```jsonc
"prefilter": {
  "enabled": true,
  "engine": "native",                        // only 'native' implements prefilter
  "dc_block": true,
  "highpass_hz": 30.0,                       // null = no subsonic filter
  "highpass_rolloff_db_per_octave": 24,      // 6|12|18|24|30|36; 24 is cited
  "decision": { "skill": "plan-prefilter", "rationale": "…", "confidence": 0.9,
                "inputs": ["analysis.json#spectral", "analysis.json#recording_info"] }
}
```

The section is **optional** in the contract: a plan that omits it entirely is
valid at schema 3.3 and behaves as disabled. Write it out anyway when you have
considered it, with the `rationale` saying you decided against — an absent section
and a considered "no" look identical in the file otherwise.

`vinyl-process lint` findings that belong here: `prefilter-no-op` (enabled with
nothing switched on — disable the section instead), `subsonic-cutoff-high` and
`subsonic-cutoff-outside-band`.

## Checkpoint

**Report the headroom recovered, and let the person decide whether it is worth
it.** That is the one thing this stage buys that can be stated as a number, and it
is why the checkpoint exists rather than the stage running on a threshold.

Render it: this stage runs before everything, so the rung is `review/prefilter/` —
the plan with `prefilter` on and `declick`, `normalize` still off, which makes it
comparable against `review/split/` by the filter alone.

```sh
vinyl-process execute plan-side-a.json --audio <recording> \
  -o review/prefilter --manifest manifest-side-a.json
```

Present:

- **the headroom**: the peak of `review/split/` against the peak of
  `review/prefilter/`, in dB. That difference *is* the gain `plan-normalize` will
  find later, so say so — the two decisions look unrelated otherwise. Where it is
  a fraction of a dB, say that too: it is an honest "this bought nothing".
- `spectral.rumble_db` before, and **re-measured on the render**:
  `vinyl-process analyze review/prefilter/<track> --analyzers spectral`. A filter
  that did what it claimed shows a materially lower figure; one that did not is
  worth knowing about before it reaches the album.
- `recording_info.dc_offset` before and after, if `dc_block` ran. It should come
  back at zero to rounding. If it does not, something else is wrong.
- **what the cited reason actually was** — subsonic energy causing clicks when
  editing — so nobody approves this expecting to hear a difference. On a
  well-behaved transfer they will not, and that is the expected outcome, not a
  failure.

Then ask the question in the terms they can answer: this removes everything below
`highpass_hz`, permanently, from the copy that becomes the album; the capture
keeps it. Is that the trade they want? A "no" here is a complete answer and costs
nothing.

Do **not** offer an A/B on sound quality. The difference is below 30 Hz, most
playback systems do not reproduce it, and asking "which sounds better" invites an
answer the audio cannot support. The comparison that means something is the
headroom figure and the re-measured `rumble_db`.

## Rules

- The stage runs on the **whole side, before `split`**, so its filter never sees a
  track edge and its transient settles in the lead-in rather than at the start of
  track 1. That position is part of what the plan means
  ([adr/0012](../../../docs/adr/0012-the-executor-has-a-pre-split-phase.md)).
- Never apply a filter yourself; the executor does. This section is the decision.
- `highpass_rolloff_db_per_octave` is stated in dB/octave and the engine converts
  it to a Butterworth order by `order = rolloff / 6`. That is a documented unit
  conversion, not a choice — do not write an order here.
- The filter runs **forward only**, so the rolloff delivered is the rolloff asked
  for. A zero-phase pass would double it, and a plan asking for 24 would get 48.
- `enabled: false` and `enabled: true` with both switches off are different
  things: the second is a plan that says it will act and then does not, and both
  `lint` and the manifest call it out. Use the first.
- A high `spectral.rumble_db` is worth telling the user about regardless of what
  this stage does — it is a turntable or a pressing problem, and it belongs
  upstream in `vinyl-archive`.
