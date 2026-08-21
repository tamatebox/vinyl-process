# DSP Engines

An engine transforms audio exactly as the plan parameterises it. It never chooses
parameters, never reads `analysis.json`, and never uses randomness or the wall
clock. The plan names the engine per stage; the executor resolves it through the
registry and refuses the run if the engine is missing, unavailable, or does not
implement the operation.

## Capabilities

In pipeline order. `prefilter` and `declick` run on the whole side, before the
cuts; the rest run per track.

| Capability | Meaning |
|---|---|
| `prefilter` | Remove DC and/or high-pass the subsonic band, on the whole side |
| `declick` | Detect and repair impulsive damage with the plan's parameters |
| `decrackle` | Repair a bed of 1-3 sample events, per sample rather than collectively |
| `mono_merge` | Fold a mono record's two groove walls onto one signal, level-matched |
| `speed` | Resample a transfer played at the wrong speed, keeping the sample rate |
| `split` | Cut the source into tracks at sample-exact boundaries, applying the plan's fades |
| `gain` | Apply a gain in dB |

An engine implements only what it has. A partial engine is a first-class citizen:

```sh
$ vinyl-process engines
ffmpeg [available] declick, gain (ffmpeg version 9.0.1 …)
native [available] declick, decrackle, gain, mono_merge, prefilter, speed, split (native …)
```

## Built-in engines

### `native` — the reproducibility baseline

Pure numpy/scipy, no external binaries, every capability.

- `split` — `AudioBuffer.slice` plus raised-cosine fades. Bit-exact: an unfaded cut
  is byte-identical to the corresponding slice of the source.
- `prefilter` — subtract each channel's mean when `dc_block` is set, then a
  Butterworth high-pass at `highpass_hz`. The plan states the rolloff in
  **dB/octave** because that is the unit the practice is stated in; the engine
  converts it by `order = rolloff / 6`, a documented unit conversion rather than a
  choice. The filter runs **forward only** (`sosfilt`), so a plan asking for 24
  dB/octave gets 24 — a zero-phase pass would deliver 48. The cost is phase shift
  and a settling transient, both below 30 Hz on a subsonic filter, and both landing
  in the lead-in because the stage runs before `split`. Determinism is unaffected.
- `declick`, algorithm `block_ratio` — high-pass the signal (default 3 kHz,
  override with `params.highpass_hz`), then flag every sample where the energy of a
  click-width window (`params.detect_ms`, 0.2 ms) exceeds the energy of its
  surrounding neighbourhood (`params.context_ms`, 40 ms) by `threshold` times.
  `threshold` is a **ratio, not a sigma count**, and has no default: it is read off
  `clicks.threshold_sweep` for the pressing in hand, and the engine refuses to run
  without it. Crossings are merged into events, each event is localised onto the
  impulse using the curvature of the unfiltered signal, events wider than
  `max_click_width_ms` are rejected as programme material, and the rest are bridged
  by autoregressive least squares (Janssen 1986) blended by `strength`.
  `params.interpolator` also offers `hermite` and `linear`; the AR order and window
  are *derived* from `max_click_width_ms` by the published rule
  (`p = 3·Nmax + 2`, window `8p`) rather than chosen, and `params.ar_order`,
  `ar_iterations` and `ar_context` override them. `params.confirm_k` is an opt-in
  second stage that discards candidates a few sinusoids already explain.
- `decrackle`, algorithm `curvature_ratio` — a sample's `|second difference|`
  against the mean `|second difference|` of its own neighbourhood
  (`params.context_ms`, 5.0). A **ratio**, so level-independent, and **local**, for
  the reasons in `adr/0010`; smaller is more aggressive, and there is no default.
  Runs wider than `max_event_width_samples` are dropped rather than repaired, so
  this stage cannot bridge anything `declick` would have found. `params.interpolator`
  is `linear` by default — across one to three samples a straight line between the
  survivors cannot leave the range they span — with `hermite` available. See
  [adr/0013](adr/0013-crackle-is-a-separate-stage-with-its-own-detector.md).
- `mono_merge` — `strategy: left | right` copies one wall to both channels;
  `level_matched` tracks each wall's level over `level_window_seconds` (1.0),
  targets their mean and averages the two. The level floor is a fraction of the
  file's own RMS, added to both estimates, so the ratio degrades to unity in
  silence rather than to noise. Output stays stereo with the same data in both
  channels. The arithmetic ceiling is 3 dB and holds only where the two walls'
  damage is independent, which the source behind the stage says it is not — so the
  ceiling is not a prediction
  ([adr/0015](adr/0015-a-mono-record-has-two-observations-of-one-signal.md)).
- `speed` — resample by `played_rpm / intended_rpm`, keeping the sample rate, so
  time and pitch scale together the way a speed error made them. The ratio is
  approximated as a rational with denominator up to 20 000; a ratio that would
  collapse to 1 on that grid is **refused** rather than silently applied as a
  no-op, which is what a coarser bound did. See
  [adr/0016](adr/0016-a-pre-split-stage-may-remap-time.md).
- `gain` — multiply by `10^(dB/20)`.

What is established, on real audio rather than injected damage:

- **The statistic is local.** Handed the same 60 s in different chunk sizes, the
  robust-sigma detector this replaced moved its answer by up to 7.8x while the
  energy ratio held to within 10 %. That is why the analyzer (which sees a side)
  and this engine (which sees one track) describe the same events — under the old
  statistic they did not, once measured at 38 693 clicks reported against 58 355
  spans repaired.
- **It finds the surface.** On a near-clean pressing used as a negative control the
  old detector claimed 1082 events a minute while finding *none* in the inter-track
  gaps, where the surface is unmasked; the ratio found few and concentrated them in
  the gaps, twelve of which were confirmed audible by ear.
- **No repair invents a level.** Every bridge is clipped into the bounds of its own
  neighbourhood. Unbounded, the cubic once bridged a 65-sample gap at twelve times
  the amplitude of its neighbourhood and three times the peak of the whole track —
  inside the width limit the plan had set.

What follows from the **structure** of the statistic rather than from any
recording, and is therefore only as strong as the code:

- **One huge transient cannot spoil the small clicks.** The question a lead-in
  raises: does the needle drop — near full scale, tens of milliseconds wide —
  degrade repair of the quiet clicks elsewhere on the side? No, and no experiment
  is needed to say so: the statistic compares a click-width window against its
  *own* 40 ms neighbourhood, so a sample outside that neighbourhood never enters
  the arithmetic. A test on **synthesised** audio confirms the implementation
  matches the claim — with a 0.95-amplitude thump inserted, every detection outside
  50 ms of it is identical, event for event — but the guarantee is the window, not
  the test. A global spread would have been dragged upwards by the one loud event
  and would then miss everything quiet, which is the failure `adr/0010` records.

  So repairing the **whole side** pre-split is safe, and **trimming the lead-in
  away first is not a prerequisite**. There *is* a shadow — a loud neighbour
  inflates the context mean — and the structure bounds it by the context window;
  how long it is on a given pressing is not something this repository has measured,
  and the fixture's ~10 ms is a property of that fixture. The drop itself is not
  repaired either: at tens of milliseconds it is wider than `max_click_width_ms`
  and is rejected as programme material.

  Where this stops holding is anything estimating a statistic over a *region*
  rather than a neighbourhood — a noise profile above all: "large clicks can
  corrupt a noise profile and make later processing pump or smear" (Sound Forge
  Pro's vinyl-restoration guide). That is a de-noise problem, solved by choosing
  the profile's region, not by trimming.

Samples outside a repaired span are left bit-identical: only the event spans are
written. What remains at a repaired site is a seam around −60 dBFS, and the
detector's threshold is relative, so re-analysing a declicked file still reports
clicks — at a much lower amplitude. Judge repair by the amplitude histogram, not by
the count, and never iterate towards `count == 0`.

Three things are **not** established. Which interpolator is better: comparisons by
SNR against damage injected here were discarded as unsound (the material, the click
shapes and the amplitudes were all chosen by the same hand that chose the
algorithm), and there is no public benchmark with clean references to appeal to.
Whether a given threshold fires on the music: the ratio does fire on some
percussive attacks, which is what the analyzer's per-rung `onset_coincidence` is
for — read it before trusting a rung, because a repair that follows the beat
interpolates over the attacks. And **how much `decrackle` and `mono_merge` are
worth on a pressing**: both have tests that they compute what they claim, and both
were checked against audio synthesised here, which the first item on this list
already explains is not evidence of benefit. Their skills are arranged around
measuring on the record in hand for that reason. Adding a real-transfer result to
this list is how that changes.

### `ffmpeg` — interchangeability, demonstrated

Requires an `ffmpeg` binary on `PATH`. Deterministic for a fixed build, whose
version string the manifest records.

- `gain` — the `volume` filter with `precision=double`. Without that flag the
  filter works internally in float and drifts ~1e-7 from the native engine; with
  it, both engines agree to double rounding.
`decrackle` is deliberately **not** offered here. ffmpeg has no crackle filter,
and mapping the stage onto `adeclick` with a narrow window was rejected rather
than overlooked: `adeclick` is impulsive-noise removal, the collective family that
the citation behind `decrackle` says is *not* attuned to crackle, so the mapping
would contradict the reference that justifies the stage
([adr/0013](adr/0013-crackle-is-a-separate-stage-with-its-own-detector.md)). An
engine implements only what it has.

`afftdn` would be the delegate for a de-noise stage, and that stage is not built.
The reason is measured, not assumed — see *Known limitations* in
[architecture.md](architecture.md): its `noise_floor` dominates the result and no
reference says what to set it to, and its own `sample_noise` start/stop commands
produced output identical to no command at all on ffmpeg 9.0.1, so a plan cannot
hand it a profile region.

- `declick`, algorithm `adeclick` — parameters are mapped deterministically and the
  mapping is part of the contract:

  | Plan field | ffmpeg option | Note |
  |---|---|---|
  | `threshold` | `t` | adeclick's own 1–100 scale, **not** sigmas |
  | `max_click_width_ms` | `w` | analysis window, clamped to 10–100 ms, at least 4× the click width |
  | `params.window_ms`, `overlap`, `ar_order`, `burst_fusion`, `method` | `w`, `o`, `a`, `b`, `m` | explicit overrides |
  | `strength` | — | no equivalent: below 1.0 the engine **refuses the plan** |

  Refusing beats silently ignoring: a dropped parameter would make the plan an
  incomplete record of what happened
  ([adr/0006-engines-refuse-what-they-cannot-honour.md](adr/0006-engines-refuse-what-they-cannot-honour.md)).

- `split` is deliberately not offered. Sample-exact cutting is what the native
  engine is for, and mixing engines across stages is supported.

Audio crosses the process boundary as float64 WAV in both directions, so the
round-trip itself is lossless.

## Adding an engine

Inside this repository:

```python
# src/vinyl_process/dsp/engines/my_engine.py
from vinyl_process.dsp.base import Capability, DspEngine


class MyEngine(DspEngine):
    name = "my-engine"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({"declick"})

    def version(self) -> str:
        return "my-engine 1.2.3"

    def is_available(self) -> bool:
        return shutil.which("my-tool") is not None

    def declick(self, audio, plan): ...
```

Register it in `dsp/registry.py::_load`. Implement only real capabilities — the
base class refuses the rest with a clear error.

From a separate distribution, no fork required:

```toml
[project.entry-points."vinyl_process.dsp_engines"]
my-engine = "my_package:MyEngine"
```

The registry loads entry points after the built-ins, logs and skips a plug-in that
raises or does not produce a `DspEngine`, and lets a plug-in shadow a built-in name
deliberately.

## Rules for any engine

1. Deterministic: same input plus same parameters gives the same bytes. No
   randomness (dither is the export's job, and it is seeded), no clock, no locale.
2. No decisions. Converting a canonical plan parameter into the engine's own units
   is fine when it is deterministic and documented; picking a value is not.
3. Refuse what you cannot honour, loudly.
4. Report an honest `version()` — it lands in the manifest and is how future drift
   gets diagnosed.
5. Never read `analysis.json`, configuration, or anything outside the arguments you
   were given. The layer test enforces this.
