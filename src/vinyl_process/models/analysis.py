"""``analysis.json`` contract: pure measurements, no decisions.

One section per registered analyzer; the section key equals the analyzer name
(enforced by ``tests/contracts/test_analyzer_sections.py``). Every section is
optional so that ``analyze --analyzers rms_profile,clicks`` produces a valid,
partial document — consumers must handle absent sections.

The document contains no timestamps by default, so analysing the same file
twice yields byte-identical JSON.

The annotated walk-through of every field is ``docs/data-contracts.md``; this
module is the source it describes.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import Field

from vinyl_process.models.common import (
    Confidence,
    ContractModel,
    Section,
    SourceInfo,
    VersionedDocument,
)

BoundaryMethod = Literal["silence", "rms_valley", "spectral_change"]
"""Detection method that produced a boundary candidate. Additive: new detectors
add a value (minor version bump)."""

AnalyzerStatus = Literal["ok", "failed", "skipped"]


# --------------------------------------------------------------------------- #
# leaf value objects
# --------------------------------------------------------------------------- #
class SilenceRegion(ContractModel):
    """A contiguous quiet stretch. Sample positions are inclusive-exclusive."""

    start_sample: int = Field(ge=0)
    end_sample: int = Field(ge=0)

    music_end_sample: int = Field(ge=0)
    """Where the music *before* this region actually stopped.

    ``start_sample`` is where the level crossed a fixed threshold, which for a
    track that fades out happens mid-fade — on one tested pressing 4 s early on
    one track and 22 s early on another. This is instead where the level has come
    down to what the region itself measures, so a cut placed here never clips a
    fade. Equal to ``start_sample`` for a region that begins at sample 0, and a
    lower bound for a region that is mostly fade rather than silence (typically
    the trailing one, where the fade and the run-out sit at the same level).
    """

    music_start_sample: int = Field(ge=0)
    """Where the music *after* this region actually starts.

    ``end_sample`` is where the level crossed the threshold, which for a track
    that fades in happens late, so a cut placed there clips the entrance. This is
    instead the last point at which the level is still on the region's own floor —
    a lower bound, erring early, because a clipped entrance cannot be recovered.

    Use it rather than a fixed pre-roll. The margin a track actually needs varies:
    across one album it ran from 0.07 s to 0.42 s, and a single figure applied to
    every track either clips an entrance or ships bare surface noise ahead of it.
    That surface is where the clicks are — the first half-second of a track
    carried up to 45 times the click density of the track itself, unmasked and cut
    from the most handled part of the record. Equal to ``end_sample`` for a region
    that runs to the last sample."""

    mean_rms_db: float
    duration_seconds: float = Field(ge=0)
    confidence: Confidence


class BoundaryCandidate(ContractModel):
    """One *candidate* cut point. Choosing among candidates is the Split
    skill's job — the analyzer never ranks them into a final track list."""

    sample: int = Field(ge=0)
    method: BoundaryMethod
    confidence: Confidence


class Histogram(ContractModel):
    """``len(bin_edges) == len(counts) + 1``, as produced by ``np.histogram``."""

    unit: str
    bin_edges: list[float]
    counts: list[int]


class BandEnergy(ContractModel):
    low_hz: float = Field(ge=0)
    high_hz: float = Field(gt=0)
    energy_db: float


class Percentiles(ContractModel):
    p05_db: float
    p50_db: float
    p95_db: float


class AnalyzerRun(ContractModel):
    """Record of one analyzer's execution, for debugging a partial document."""

    name: str
    version: str
    status: AnalyzerStatus
    message: str | None = None
    duration_ms: float | None = None  # only with --timings; breaks byte equality


# --------------------------------------------------------------------------- #
# sections (one per analyzer)
# --------------------------------------------------------------------------- #
class RecordingInfoSection(Section):
    """Electrical and format characteristics of the capture itself."""

    subtype: str
    bit_depth: int | None = None
    dc_offset: list[float]
    channel_peak_db: list[float]
    channel_rms_db: list[float]
    channel_balance_db: float | None = None
    channel_correlation: float | None = None


class RmsProfileSection(Section):
    """Windowed loudness envelope; the basis for silence and valley detection."""

    window_seconds: float = Field(gt=0)
    hop_seconds: float = Field(gt=0)
    values_db: list[float]


class BandLevels(ContractModel):
    """One frequency band's level over time, plus the band's own floor."""

    low_hz: float = Field(ge=0)
    high_hz: float = Field(gt=0)
    floor_db: float
    """A low percentile of ``values_db`` — what this band reads where nothing is
    happening in it, which is not the same figure for every band."""
    values_db: list[float]


class BandProfileSection(Section):
    """Windowed RMS per frequency band — which bands carry the energy, over time.

    Broadband level cannot tell a band-limited entrance from surface noise,
    because both can sit at the same dBFS: the surface's energy piles into one
    band — on a played LP usually the lowest, since RIAA playback boosts the bass
    of a groove noise that was already there — and that band sets the broadband
    figure, so a filtered intro 30 dB up in 400-3000 Hz moves it by a fraction of
    a dB. Per band it is unmissable. ``spectral`` measures the same axis but
    averages the whole file, and ``rms_profile`` measures over time but sums the
    bands, so neither can be read frame by band.

    Read a **step in one band while its neighbours hold still**, not the tilt of
    the spectrum: continuous groove noise is weighted low and impulsive abrasion
    is broadband, so the tilt says what kind of surface it is, not whether the
    stretch is programme.

    Frames follow ``rms_profile``'s convention: frame ``i`` covers
    ``[i*hop, i*hop + window)`` in samples from 0, so with equal hops the two
    sections index alike. A band whose lower edge is at or above Nyquist is
    omitted; the requested edges stay in ``meta.params`` either way.
    """

    window_seconds: float = Field(gt=0)
    hop_seconds: float = Field(gt=0)
    bands: list[BandLevels]


class SurfaceNoiseSection(Section):
    noise_floor_db: float
    stability_db: float = Field(ge=0)


class SilenceSection(Section):
    threshold_db: float
    regions: list[SilenceRegion]


class BoundariesSection(Section):
    """Candidates plus the playable region.

    ``lead_out_start_sample`` is where the trailing silence begins — for a
    full-side recording this is the run-out groove.
    """

    candidates: list[BoundaryCandidate]
    lead_in_end_sample: int | None = None
    lead_out_start_sample: int | None = None


class ThresholdPoint(ContractModel):
    """One rung of the detector's threshold ladder."""

    threshold: float = Field(gt=0)
    count: int = Field(ge=0)
    rate_per_minute: float = Field(ge=0)
    silence_rate_per_minute: float | None = Field(default=None, ge=0)
    programme_rate_per_minute: float | None = Field(default=None, ge=0)

    revolution_r: float | None = None
    """Phase concentration of this rung's detections on the platter's period —
    ``[analyzer.clicks] revolution_seconds``. 0 is evenly spread, 1 is all struck
    at the same point of the turn."""

    revolution_lock: float | None = None
    """Rayleigh's ``n*r**2`` for the same figure. Its null distribution is
    exponential with mean 1 regardless of how many detections there are, so rungs
    are comparable: 3 is suggestive, 5 strong.

    A high value means a defect crossing the groove spiral, struck once per
    revolution. That is surface damage of the most audible kind and the one case
    where periodic detections must be *kept* — reading "periodic" as "musical"
    would discard exactly the clicks a listener notices most."""

    onset_coincidence: float | None = None
    """How much more often than chance this rung's detections sit on a rising
    edge. 1.0 means the detector is indifferent to note attacks; large means it is
    following the music, and the repair would interpolate over the attacks.

    Read it beside the two rates, because they do not catch this. On one pressing
    a rung whose silence rate beat its programme rate 43.8 to 1 still landed on
    onsets 7.8 times more often than chance."""


class ClicksSection(Section):
    count: int = Field(ge=0)
    rate_per_minute: float = Field(ge=0)
    amplitude_histogram: Histogram
    width_histogram: Histogram
    density_per_minute: list[float]

    silence_rate_per_minute: float | None = Field(default=None, ge=0)
    """Detection rate inside the silent stretches between tracks, where there is
    nothing but the record's own surface. ``None`` when silence was not measured."""

    programme_rate_per_minute: float | None = Field(default=None, ge=0)
    """Detection rate where music is playing.

    Read together with :attr:`silence_rate_per_minute` this separates a worn
    pressing (both rates high) from a detector over-triggering on the material
    (only the programme rate high) — a distinction the count alone cannot make,
    and one that decides whether declicking helps or dulls the record.
    """

    threshold_sweep: list[ThresholdPoint] = Field(default_factory=list)
    """The same detector run across a ladder of thresholds.

    No single threshold suits every pressing — on one album measured here the two
    sides wanted different values, and a collection spans near-mint to heavily
    worn. So the threshold is not fixed by the analyzer: the ladder is reported as
    the fact, and the plan-declick skill picks the rung, per record, with whoever
    owns it. Read the curve rather than the headline `count`, which is only the
    rung named by ``meta.params.threshold_ratio``.

    What the curve shows: at a threshold too low the programme rate swamps the
    silence rate, which means the detector is following the music; at one too high
    nothing is found even in the inter-track gaps, where there is no music to
    find. The operating point is between, and it is legible per side.
    """

    positions_sample: list[int]
    positions_truncated: bool = False


class PeaksSection(Section):
    peak_db: float
    peak_sample: int = Field(ge=0)
    true_peak_db: float | None = None
    """4x-oversampled estimate of the reconstructed waveform's ceiling, in dBTP.
    Never below ``peak_db``; a resampler or a lossy encoder can turn the
    difference into a real, clipping sample. ``None`` when the recording is too
    short to oversample meaningfully."""

    rms_db: float
    gated_rms_db: float | None = None
    """RMS of the programme only, on BS.1770-4's gating geometry and without its
    K-weighting. ``rms_db`` averages the inter-track gaps and the lead-in in
    too, so the two differ by however much silence the side carries."""

    lufs: float | None = None
    """Integrated loudness in **LUFS** — BS.1770's K-weighting, its channel
    weighting and both its gates. The same geometry as ``gated_rms_db`` with the
    filter that separates a level from a loudness, so the two differ by the
    K-weighting's verdict on this material's spectrum: a bright side reads
    *louder* in LUFS than its dBFS level suggests, a bass-heavy one quieter.

    ``None`` when the recording is shorter than one 400 ms gating block. This is
    the figure ``normalize.mode: album_lufs`` aims, and it is measured over the
    whole recording, so it includes the lead-in and the run-out that the cuts
    discard — the executor re-measures on the split audio."""

    crest_factor_db: float


class DynamicRangeSection(Section):
    dr_estimate_db: float
    loud_rms_db: float
    percentiles: Percentiles


class ClippingSection(Section):
    clipped_sample_count: int = Field(ge=0)
    clipped_region_count: int = Field(ge=0)
    longest_run_samples: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)


class SpectralSection(Section):
    centroid_mean_hz: float
    centroid_std_hz: float
    rolloff_mean_hz: float
    rumble_db: float
    hiss_db: float
    bands: list[BandEnergy]


class TransientsSection(Section):
    """Transient density over time — how percussive the material is, which
    tells the Declick skill how much false-positive risk a threshold carries."""

    hop_seconds: float = Field(gt=0)
    density_per_second: list[float]
    mean_per_second: float = Field(ge=0)
    peak_per_second: float = Field(ge=0)


class PeriodPeak(ContractModel):
    """One autocorrelation peak of the onset-strength envelope."""

    period_seconds: float = Field(gt=0)
    r: float


class RevolutionCorrelation(ContractModel):
    """Correlation at one turntable speed's revolution period.

    Named speeds rather than discovered ones, in the same spirit as
    ``spectral.bands``: how strongly this window repeats at exactly one turn of
    the disc is a fact about the recording, and which speed the record actually
    is remains the reader's to conclude.
    """

    rpm: float = Field(gt=0)
    period_seconds: float = Field(gt=0)
    r: float


class PeriodicityWindow(ContractModel):
    """One probe window. Positions are inclusive-exclusive."""

    start_sample: int = Field(ge=0)
    end_sample: int = Field(ge=0)

    peaks: list[PeriodPeak]
    """Strongest autocorrelation peaks, ordered by ``r``."""

    baseline_r: float
    """Median correlation across the search range — the floor the peaks stand on.

    Subtract it before comparing peaks between windows. It is not itself a mark
    of surface noise: on a tested side the crackling lead-in sat at 0.17-0.23
    while the run-out groove, whose tick is far cleaner, sat at -0.03, and quiet
    programme reached 0.24."""

    revolution: list[RevolutionCorrelation]
    """Correlation at each configured revolution period."""


class PeriodicitySection(Section):
    """How periodic the material is, window by window.

    Answers one question the level envelope cannot: is a quiet stretch faint
    music or the record's own surface? A groove defect repeats once per
    revolution — 1.8 s at 33 1/3 rpm, 1.333 s at 45 — and never on the beat, so a
    window topped by the revolution period is the pressing rather than the
    performance, however loud or bright it is. This reports the correlations; the
    reading is the caller's.

    Compare a window's own top peak against its ``revolution`` entries: where a
    revolution correlation rivals the top peak, the window is surface. Two things
    that look like they should work do not. A single correlation taken at
    ``programme_period_seconds`` does not — on a tested side the whole-programme
    estimate landed on the bar while individual windows expressed the sub-beat,
    so the comparison separated nothing. Nor does ``baseline_r`` alone; see there.
    """

    onset_hop_seconds: float = Field(gt=0)
    window_seconds: float = Field(gt=0)
    window_hop_seconds: float = Field(gt=0)
    min_period_seconds: float = Field(gt=0)
    max_period_seconds: float = Field(gt=0)

    programme_period_seconds: float | None = None
    """Dominant onset period over everything the silence detector did not claim —
    the beat, or a multiple of it. Falls back to the whole recording when the
    detector claims all of it. Context, not a threshold."""

    programme_peak_prominence: float | None = None
    """Median ``top peak r - baseline_r`` across windows lying wholly inside the
    programme: what a window of this record's music looks like, measured the same
    way as every window below, so the two are comparable."""

    windows: list[PeriodicityWindow]


class RunOutSection(Section):
    """Where the music stops and the run-out groove begins.

    ``silence`` cannot answer this and does not claim to. Its
    ``regions[-1].music_end_sample`` is the first frame within
    ``settle_margin_db`` of the *quietest* level in the region, and a trailing
    region routinely holds two floors: the run-out groove, and the needle lift
    after it. Then the minimum belongs to the lift and no frame of the run-out
    reaches it. Measured on a 2xLP whose sides D, B and C all did this, the answer
    came back at the end of the file — **27 s** past the real music end on side D.
    ``boundaries.lead_out_start_sample`` is no substitute either: it is a level
    crossing, and it fired 9.3 s and 5.0 s early on two sides of the same record,
    both times inside a closing fade.

    What separates the two is not level. It is the platter: a groove defect
    repeats once per revolution and music does not, so ``periodicity`` says where
    the programme stopped, and ``band_profile`` refines that to a frame by asking
    where every band has arrived at the run-out's own level. Both are measurements
    already in the document; this section is the two of them read together.

    ``start_sample`` is ``None`` when the recording has no run-out to find — it
    ends in music, or `periodicity` found no window that looked like programme.
    """

    start_sample: int | None = Field(default=None, ge=0)
    """First sample of the run-out groove, i.e. where the music has stopped. The
    figure a last cut should be placed from."""

    anchor_sample: int | None = Field(default=None, ge=0)
    """Start of the last `periodicity` window whose own top autocorrelation peak
    still beat the platter's revolution correlations — the coarse answer, before
    `band_profile` refined it. Reported because the refinement can only move the
    answer later, so the two together bracket it."""

    run_out_band_levels_db: list[float] = Field(default_factory=list)
    """The run-out's own level in each `band_profile` band, which is the reference
    `start_sample` was measured against. Read it against the bands' `floor_db` to
    see how far above the file's own floor this record's run-out sits."""


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
class AnalysisDocument(VersionedDocument):
    document_type: Literal["analysis"] = "analysis"
    generated_by: str
    source: SourceInfo
    config_digest: str | None = None
    analyzers: list[AnalyzerRun] = Field(default_factory=list)

    recording_info: RecordingInfoSection | None = None
    rms_profile: RmsProfileSection | None = None
    band_profile: BandProfileSection | None = None
    surface_noise: SurfaceNoiseSection | None = None
    silence: SilenceSection | None = None
    boundaries: BoundariesSection | None = None
    clicks: ClicksSection | None = None
    peaks: PeaksSection | None = None
    dynamic_range: DynamicRangeSection | None = None
    clipping: ClippingSection | None = None
    spectral: SpectralSection | None = None
    transients: TransientsSection | None = None
    periodicity: PeriodicitySection | None = None
    run_out: RunOutSection | None = None

    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def section_fields(cls) -> tuple[str, ...]:
        """Field names holding analyzer sections, i.e. ``X | None`` where ``X``
        derives from :class:`Section`. Analyzer names must match these."""
        names: list[str] = []
        for name, field in cls.model_fields.items():
            for arg in get_args(field.annotation):
                if isinstance(arg, type) and issubclass(arg, Section):
                    names.append(name)
                    break
        return tuple(names)
