# 0022 — Declick decides on the mean and repairs a shared span

**Status**: proposed — the first record here that is not yet accepted. It exists to
hold the measurements and to name the decision, because implementing it changes
the output bytes of every plan with `declick` enabled and
`docs/architecture.md` has said since [0015](0015-a-mono-record-has-two-observations-of-one-signal.md)
that it "needs its own decision rather than being slipped in".

## Context

`native`'s `declick` detects on `audio.mono()` — the channel mean — and repairs
every channel over the same span. The reference implementation does not: the
ClickRepair 3.9 manual makes "decisions on click detection and repair in the two
channels… independently".

Measured on one 2xLP, at the rung that shipped (`block_ratio`, threshold 75). Of
246 repairs inside the exported cuts, 27 changed the audio by more than −20 dBFS
and 22 of those 27 were in one track. **Two of them survived the repair**, and the
detector still reports them afterwards at a level it should have caught:

| position | before (mean / L / R) | after (mean / L / R) |
|---|---|---|
| 1:07.36 | 157 / 158 / 147 | **75 / 137 / 149** |
| 1:16.36 | 131 / 133 / 86 | **76 / 136 / 163** |

The mean came down and the individual channels did not. Ten other audible repairs
on the same record cleared properly in all three figures, so this is not the
algorithm failing generally.

**The span is what is wrong, not the detection.** At 1:07.36 the repaired span was
17 samples; the surviving impulse in the left channel peaks **one sample before
the span begins**, and in the right channel **eleven samples after it ends** —
both in audio the repair never touched. The detector had found the event
emphatically (mean ratio 157 against a threshold of 75). What it got wrong was how
far the event reached in each channel, because the span comes from a statistic
computed on the mean, where a click that hits the two walls at slightly different
offsets partly cancels.

**Nothing available in a plan reaches it.** Every lever was rendered on the side
and measured at the two positions:

| tried | result at the two residuals | cost elsewhere |
|---|---|---|
| rung 50 | **byte-identical** | one track's in-cut gap rate inverted below its programme rate, `onset_coincidence` 18.22 |
| rung 35 + `confirm_k` 5 | identical | that track fell to 22 spans from 87 |
| `confirm_k` 3 | identical | onset bias 18.2 → 17.3 only |
| `confirm_k` 5 | identical, **and two good repairs reverted** | 87 → 17 spans |
| `detect_ms` 0.4 | identical | 87 → 38 spans; two good repairs reverted |
| `detect_ms` 0.6 | — | repaired nothing at all |
| `interpolator` hermite / linear | ±13 in the ratio, both directions | not a fix |
| `max_click_width_ms` 2 → 8 ms | — | **0 new detections**, so wide damage is not the explanation |

The threshold cannot help because `_localise` narrows each span using curvature
against `6σ`, and rungs 50 and 75 converge on the same span. `strength` and the
interpolator cannot help because they only act *inside* the span. So the ceiling is
structural, and the shipped rung is the best of everything measured — most spans on
the damaged track, the lowest onset bias of any variant, and no variant improving
the residual.

**Why this is not simply "detect per channel".** [0010](0010-the-click-statistic-is-local.md)
replaced the previous detector so that "the statistics a skill reasons about and
the damage the engine repairs are the same events by construction". `clicks`
computes its sweep on the mean. Move detection in the engine to per-channel and
that correspondence breaks: `plan-declick` chooses a rung from
`clicks.threshold_sweep`, and the sweep would no longer describe what the engine
will do. Restoring it means a per-channel sweep, which changes the shape of the
`clicks` section — a contract change, and the rung ladder's two rates, two
statistics and three histograms would all have to become per-channel or be
redefined.

## Decision

Undecided. The options, with what each costs:

1. **Localise the span per channel, keep detection on the mean.** The minimal
   change that addresses what was actually measured. `click_events_block` would
   still find events on the mean, so `clicks.threshold_sweep`, every rate and
   every histogram keep describing exactly the events the engine repairs and
   [0010](0010-the-click-statistic-is-local.md) is untouched; only `_localise`
   would run per channel, per event, widening or shifting each channel's span on
   its own curvature. No schema change, no analyzer change, no new plan field.
   Output bytes change for every plan with `declick` enabled. **This is the
   option this record's measurements argue for**, because the residual is a span
   error and not a detection error.
2. **Detect and repair per channel, and make `clicks` per-channel to match.**
   What the reference does. Costs a contract change to the `clicks` section, a
   redefinition of the sweep `plan-declick` reads, and the same output-byte break.
   Buys the case option 1 does not cover: a click loud in one wall and absent from
   the other, which the mean halves and may push under the rung.
3. **Detect per channel in the engine only.** Cheapest to write and the one to
   avoid: it silently breaks the correspondence 0010 exists to guarantee, and
   every rung choice becomes an estimate again without anything reporting it.
4. **Do nothing.** Keep the limitation documented. The residual is two events on
   one track of one record, and the person who owns that record, told what
   remained and why, chose to accept it — over-repair changes the original sound,
   and the shipped rung already sits 13-25× below the practitioner repair-rate
   band.

## Consequences

Of accepting **1** or **2**:

- **Reproducibility breaks by design for archived plans.** Any manifest written
  with `declick` enabled will no longer reproduce, exactly as when `declick` moved
  pre-split in [0012](0012-the-executor-has-a-pre-split-phase.md). That is a
  contract event: `manifest.stages[]` records the order but not the span rule, so
  the engine version is the only marker of the era and must be bumped.
- **The benefit is an inference, not a measurement.** The per-channel ratios above
  say the detector *can* see what remains. Nothing here shows that repairing it
  sounds better, and this project's rules are explicit that a synthesised
  demonstration of benefit is unsound — the material, the damage shape and its
  density would all be chosen by the same hand. A real pressing with a known-clean
  reference would settle it and none exists here.
- **`mono_merge` gains nothing from either.** [0015](0015-a-mono-record-has-two-observations-of-one-signal.md)
  notes that per-channel repair is what would let a mono record's two observations
  be used, and that remains true, but the source behind that stage says the walls'
  damage is *not* independent — "a scratch in one wall will have consequences in
  both channels" — so the 3 dB arithmetic ceiling is not what is on offer.
- Of accepting **4**: `docs/architecture.md` keeps the entry, and
  `docs/processed-records.md` keeps the two rows recording that six plan-level
  variants were rendered and none reached it. A third record with the same
  residual would be the argument to reopen this.
