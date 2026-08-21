# Analyzers

An analyzer is a pure function `AnalyzerContext -> Section`. It measures and
nothing else: it must not choose processing parameters, write files, or look at
anything outside its context.

## What ships

| Analyzer | Requires | Measures |
|---|---|---|
| `recording_info` | — | container subtype and bit depth, DC offset, per-channel peak/RMS, channel balance, stereo correlation |
| `rms_profile` | — | windowed RMS envelope in dBFS |
| `band_profile` | — | windowed RMS per frequency band, and each band's own floor — which part of the spectrum carries the energy, over time |
| `surface_noise` | `rms_profile` | noise-floor level and how stable it is |
| `silence` | `rms_profile`, `surface_noise` | quiet regions relative to the measured floor, and where the music around each one actually stopped and started (`music_end_sample`, `music_start_sample`) |
| `boundaries` | `rms_profile`, `silence` | candidate cut points (silence, RMS valleys, spectral change) plus the playable region |
| `clicks` | `silence` | count, rate, amplitude and width histograms, density per minute, rate in gaps versus under the programme, positions |
| `peaks` | — | sample peak and its position, 4x-oversampled true peak, overall and gated RMS, crest factor |
| `dynamic_range` | `rms_profile`, `peaks` | peak-to-loud-RMS estimate and the RMS distribution |
| `clipping` | — | full-scale sample runs, longest run, ratio |
| `spectral` | — | centroid, roll-off, rumble, hiss, band energies |
| `transients` | — | onset density per second |
| `periodicity` | `silence` | onset-envelope autocorrelation per window: the strongest periods, the baseline they stand on, and the correlation at each turntable speed's revolution period |
| `run_out` | `band_profile`, `periodicity` | where the music stops and the run-out groove begins — the anchor `periodicity` gives, refined to a frame by `band_profile` |

`vinyl-process analyzers --json` prints this with each analyzer's version and
default parameters.

## Registration

```python
from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import MySection
from vinyl_process.models.common import SectionMeta


@analyzer(
    name="my_measurement",          # must equal the AnalysisDocument field name
    version="1.0",
    description="One line, shown by `vinyl-process analyzers`.",
    requires=("rms_profile",),      # resolved and ordered automatically
    defaults={"window_seconds": 0.5},
)
def analyze_my_measurement(context: AnalyzerContext) -> MySection:
    profile = context.typed_section("rms_profile", RmsProfileSection)
    window = context.number("window_seconds")   # defaults + config overrides
    ...
    return MySection(meta=SectionMeta(confidence=0.8), ...)
```

Then:

1. add `my_measurement: MySection | None = None` to `AnalysisDocument`;
2. import the module in `analyzer/registry.py::_ensure_builtins`;
3. regenerate the schemas: `vinyl-process schemas -o schemas/`.

`tests/contracts/test_analyzer_sections.py` fails if an analyzer has no section or
a section has no analyzer, so the two halves cannot drift apart.

## What the runner does for you

- resolves the dependency order, and rejects cycles;
- merges declared `defaults` with `[analyzer.<name>]` config overrides, rejecting
  unknown keys as typos;
- stamps `meta.analyzer`, `meta.version` and `meta.params` onto the returned
  section (your `meta.confidence` is preserved);
- records an `ok` / `failed` / `skipped` entry in `analyzers[]` — one broken
  analyzer degrades the document instead of losing the whole run;
- keeps the document free of timestamps so it stays byte-reproducible.

## Guidelines

- **Report, never advise.** `"clipping: 2 region(s)"` is a measurement;
  `"re-record at a lower gain"` is a decision and belongs to a skill.
- **Set a confidence** whenever the number is an estimate rather than a direct
  reading, and say what it means in the section's docstring.
- **Expose parameters** through `defaults` rather than module constants, so they are
  configurable and recorded in `meta.params`.
- **Keep series small enough to read.** `rms_profile` at a 0.1 s hop is ~12 000
  values for a 20-minute side; that is acceptable, a per-sample series is not.
- **Share maths with DSP through `signal_ops.py`**, never by importing the DSP
  layer — that is what keeps detection and repair consistent without coupling.
