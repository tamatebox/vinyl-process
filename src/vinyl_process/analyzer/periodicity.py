"""Periodicity — whether a stretch repeats on the beat or on the revolution.

The Split skill needs this, because neither level nor spectrum settles where a
side's music ends. Both failed on one 2023 12", in opposite directions.

Side Y ended in a dub outro that sat at the surface-noise level, so the level
threshold called it the run-out groove and put ``lead_out_start_sample`` 22 s
early; cutting there would have chopped the end off the track. Side X opened with
a scuffed lead-in groove 25 dB brighter than the run-out in the 3-8 kHz band —
brighter than the music too — so the spectrum argued the track started 20 s
before it did, and a printed duration that happened to fit encouraged the error.

Periodicity settles both, and settles them the same way: a groove defect repeats
once per revolution and never on the beat. The quiet outro correlated at the
track's own 0.939 s, more strongly than the loud body did once the surface
stopped masking it; the lead-in correlated at 1.333 s, one turn of a 45 rpm disc.

Measurement only: this reports the correlations and says nothing about which
windows are music, which is the Split skill's decision to make.
"""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import (
    PeriodicitySection,
    PeriodicityWindow,
    PeriodPeak,
    RevolutionCorrelation,
    SilenceSection,
)
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import correlation_at, onset_flux, periodicity_peaks


@analyzer(
    name="periodicity",
    version="1.0",
    description="Onset-envelope autocorrelation per window — beat versus revolution.",
    requires=("silence",),
    defaults={
        "onset_window_seconds": 0.02,
        "onset_hop_seconds": 0.005,
        "window_seconds": 12.0,
        "window_hop_seconds": 4.0,
        "min_period_seconds": 0.25,
        "max_period_seconds": 4.0,
        "top_k": 3,
        # The two speeds a 12" can be cut at. A measurement grid, not a choice:
        # both are reported and neither is asserted to be the record's own.
        "revolution_periods_seconds": [1.8, 1.3333],
    },
)
def analyze_periodicity(context: AnalyzerContext) -> PeriodicitySection:
    audio = context.audio
    silence = context.typed_section("silence", SilenceSection)

    onset_hop = context.number("onset_hop_seconds")
    window_seconds = context.number("window_seconds")
    window_hop = context.number("window_hop_seconds")
    min_period = context.number("min_period_seconds")
    max_period = context.number("max_period_seconds")
    top_k = context.integer("top_k")
    revolution_periods = context.numbers("revolution_periods_seconds")

    mono = audio.mono()
    flux = onset_flux(
        mono,
        audio.sample_rate,
        window_seconds=context.number("onset_window_seconds"),
        hop_seconds=onset_hop,
    )
    hop_samples = max(1, round(onset_hop * audio.sample_rate))
    frame_rate = audio.sample_rate / hop_samples

    section = PeriodicitySection(
        meta=SectionMeta(confidence=0.7),
        onset_hop_seconds=onset_hop,
        window_seconds=window_seconds,
        window_hop_seconds=window_hop,
        min_period_seconds=min_period,
        max_period_seconds=max_period,
        windows=[],
    )
    if flux.size == 0:
        return section

    def frames_of(start_sample: int, end_sample: int) -> slice:
        return slice(
            max(0, start_sample // hop_samples),
            min(flux.size, end_sample // hop_samples),
        )

    # The beat, measured where the music plainly plays: everything the silence
    # detector did not claim. Taking it over the whole side instead would let a
    # long run-out pull the estimate onto the revolution period.
    programme = np.zeros(flux.size, dtype=bool)
    programme[frames_of(0, len(mono))] = True
    for region in silence.regions:
        programme[frames_of(region.start_sample, region.end_sample)] = False
    if not programme.any():
        # Every frame claimed as silence — a recording quiet enough throughout
        # that the threshold sits above its own music. The whole side is then the
        # best estimate available, and far better than reporting nothing.
        programme[:] = True
    peaks, _ = periodicity_peaks(flux[programme], frame_rate, min_period, max_period, top_k=1)
    if peaks:
        section.programme_period_seconds = round(peaks[0][0], 4)

    step = max(1, round(window_hop * audio.sample_rate))
    span = max(step, round(window_seconds * audio.sample_rate))
    prominences: list[float] = []
    for start in range(0, max(1, len(mono) - span + 1), step):
        stop = min(len(mono), start + span)
        window = frames_of(start, stop)
        segment = flux[window]
        peaks, baseline = periodicity_peaks(
            segment, frame_rate, min_period, max_period, top_k=top_k
        )
        if not peaks:
            continue
        section.windows.append(
            PeriodicityWindow(
                start_sample=start,
                end_sample=stop,
                peaks=[PeriodPeak(period_seconds=round(p, 4), r=round(r, 4)) for p, r in peaks],
                baseline_r=round(baseline, 4),
                revolution=[
                    RevolutionCorrelation(
                        rpm=round(60.0 / period, 2),
                        period_seconds=period,
                        r=round(correlation_at(segment, round(period * frame_rate)), 4),
                    )
                    for period in revolution_periods
                    if period > 0.0
                ],
            )
        )
        if programme[window].all():
            prominences.append(peaks[0][1] - baseline)

    if prominences:
        section.programme_peak_prominence = round(float(np.median(prominences)), 4)
    return section
