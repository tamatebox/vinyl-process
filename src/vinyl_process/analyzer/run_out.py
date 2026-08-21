"""Where the music stops and the run-out groove begins.

Two measurements already in the document, read together. ``periodicity`` says
*roughly* where the programme stopped, because a groove defect repeats once per
revolution and music does not; ``band_profile`` refines that to a frame, because
a run-out has a level in every band and the approach to it from above is
monotone. Neither can do it alone, and neither could ``silence`` — see
:class:`~vinyl_process.models.analysis.RunOutSection` for what went wrong when
that was tried.

The anchor does the work that a human otherwise does by eye. Six formulations of
this measurement were written against one 2xLP before this one: three that
patched ``silence._music_end`` and three that compared bands against a
whole-file reference. All six failed, and they failed for the same reason —
without an anchor, "every band has settled to the run-out's level" is also true
of every inter-track gap, so the rule needs to be told where to start looking.
The band comparison was never the hard part.

**This technique has no outside citation and is not what the field does.** What
*is* standard practice is the decision it serves — trim the run-out, do not cut
into it — and that is cited where it is acted on, in ``plan-split``. What is
standard *practice* for finding the boundary is a level threshold plus a person
looking at a waveform: Audacity, VinylStudio and Wave Corrector all detect track
breaks from silence and expect the operator to adjust them. No tool was found
that locates the run-out by correlating against the platter's revolution period.
The underlying phenomenon is common knowledge — a groove defect is struck once
per turn, which is why locked and ticking run-outs are a thing people discuss —
but reading it as a *boundary detector* is this repository's own construction,
inherited from ``periodicity``, which was itself built in-house for a dub side
where level had already failed. Treat it as uncalibrated against the field, and
as measured only against the four sides in its tests and its originating record.
The decision, the six formulations that failed before it and the parameter plateau
are ``docs/adr/0021-the-trailing-edge-is-measured-by-the-platter-not-the-level.md``.
"""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import (
    BandProfileSection,
    PeriodicitySection,
    RunOutSection,
)
from vinyl_process.models.common import SectionMeta


@analyzer(
    name="run_out",
    version="1.0",
    description="Where the music stops and the run-out groove begins.",
    requires=("band_profile", "periodicity"),
    defaults={
        # How far a window's own top autocorrelation peak must beat the platter's
        # revolution correlations to still count as programme. THE ONLY SENSITIVE
        # PARAMETER HERE, and the one number in this analyzer worth arguing about:
        # measured across the four sides of one 2xLP, every value from 1.4 to 10.0
        # gave an identical answer on all four, while 1.2 and below put side A's
        # anchor 22.6 s late. 1.5 is a step off that cliff and inside a plateau
        # seven times wider than itself. In-house, like the three below.
        "programme_peak_factor": 1.5,
        # The run-out's own level per band is the median over this much of the
        # file's tail. A median rather than a minimum so the needle lift, which is
        # a small fraction of it, does not set the reference — which is exactly
        # the mistake `silence` makes. 20, 30 and 40 s all gave the same answer.
        "trailing_seconds": 30.0,
        # How close to that level counts as arrived, and over how long a running
        # median. 1.5-6 dB and 0.5-2 s all gave the same answer; the smoothing is
        # there so one run-out tick cannot end the search early.
        "settle_margin_db": 3.0,
        "smoothing_seconds": 1.0,
    },
)
def analyze_run_out(context: AnalyzerContext) -> RunOutSection:
    bands = context.typed_section("band_profile", BandProfileSection)
    periodicity = context.typed_section("periodicity", PeriodicitySection)
    sample_rate = context.audio.sample_rate

    if not bands.bands or not periodicity.windows:
        return RunOutSection(meta=SectionMeta(confidence=0.0))

    levels = np.array([band.values_db for band in bands.bands], dtype=np.float64)
    num_frames = levels.shape[1]
    hop_seconds = bands.hop_seconds

    trailing = max(1, round(context.number("trailing_seconds") / hop_seconds))
    reference = np.median(levels[:, max(0, num_frames - trailing) :], axis=1)
    band_levels = [round(float(value), 2) for value in reference]

    index = _anchor_index(periodicity, context.number("programme_peak_factor"))
    if index is None:
        # Nothing looked like programme, so there is no music end to report. A
        # recording that is all run-out, or all surface, lands here.
        return RunOutSection(meta=SectionMeta(confidence=0.0), run_out_band_levels_db=band_levels)
    if index == len(periodicity.windows) - 1:
        # The last window of the recording still looks like programme, so the
        # music never stopped and no run-out was captured. Reporting one anyway
        # would truncate the music, and the level cannot catch this: with no
        # run-out in the file the trailing reference is the *music's* own level,
        # which the music then trivially satisfies.
        return RunOutSection(meta=SectionMeta(confidence=0.0), run_out_band_levels_db=band_levels)
    anchor = periodicity.windows[index].start_sample

    smoothing = max(1, round(context.number("smoothing_seconds") / hop_seconds))
    smoothed = _running_median(levels, smoothing)
    ceiling = (reference + context.number("settle_margin_db"))[:, None]
    settled = np.asarray((smoothed <= ceiling).all(axis=0))

    first_frame = min(round(anchor / sample_rate / hop_seconds), num_frames - 1)
    frame = next((f for f in range(first_frame, num_frames) if settled[f]), None)
    if frame is None:
        # The programme runs to the last sample: no run-out was captured.
        return RunOutSection(
            meta=SectionMeta(confidence=0.0),
            anchor_sample=anchor,
            run_out_band_levels_db=band_levels,
        )

    start = round(frame * hop_seconds * sample_rate)
    # The anchor is a window start, so it is at or before the answer; the two
    # bracket it, and how wide that bracket is says how well they agree.
    bracket_seconds = (start - anchor) / sample_rate
    confidence = float(np.clip(1.0 - bracket_seconds / periodicity.window_seconds, 0.3, 0.95))

    return RunOutSection(
        meta=SectionMeta(confidence=round(confidence, 2)),
        start_sample=start,
        anchor_sample=anchor,
        run_out_band_levels_db=band_levels,
    )


def _anchor_index(periodicity: PeriodicitySection, factor: float) -> int | None:
    """Index of the last window that still looked like programme.

    The index rather than the sample, because whether it is the *final* window is
    what tells a side that ends in a run-out from one that ends in music.

    A window is programme where its own strongest onset period correlates better
    than the platter's revolution periods do, by ``factor``. That is the question
    ``periodicity`` exists to answer, and asking it per window rather than against
    ``programme_period_seconds`` matters: on a tested side the whole-programme
    estimate landed on the bar while individual windows expressed the sub-beat.

    Taking the *last* such window rather than the first surface-looking one is
    deliberate. A quiet passage mid-side can read as surface for a window or two,
    and stopping there would report a run-out in the middle of the record.
    """
    anchor: int | None = None
    for index, window in enumerate(periodicity.windows):
        top = window.peaks[0].r if window.peaks else -1.0
        revolution = max((entry.r for entry in window.revolution), default=-1.0)
        if top > factor * max(revolution, 0.0):
            anchor = index
    return anchor


def _running_median(levels: np.ndarray, frames: int) -> np.ndarray:
    """Per-band running median, edges replicated rather than zero-padded.

    Zero-padding a *decibel* series pulls the edge frames towards 0 dB, which on
    the trailing frames is a swing of eighty-odd dB in the wrong direction — and
    the trailing frames are the whole point here.
    """
    if frames <= 1:
        return levels
    pad = frames // 2
    padded = np.pad(levels, ((0, 0), (pad, pad)), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, frames, axis=1)
    return np.asarray(np.median(windows, axis=2), dtype=np.float64)
