"""Run-out accuracy: where the music stops, on a side that ends three ways.

The case comes from a real 2xLP. Its trailing silence region held the run-out
groove *and* the needle lift after it, so ``silence``'s ``music_end_sample`` —
the first frame within 3 dB of the region's quietest level — chased the lift and
came back at the end of the file, **27 s** past the real music end, on three of
the four sides. ``boundaries.lead_out_start_sample`` was no better from the other
direction: a level crossing, it fired 9.3 s and 5.0 s early on two sides, both
times inside a closing fade.

So the fixture builds the shape that breaks both: music, a quiet outro at the
surface's own level, a run-out with a once-per-revolution tick, and a needle lift
after it. Ground truth is where the run-out was constructed to begin, and
``test_the_lift_is_what_breaks_the_level_marker`` asserts the other half — that
the marker this replaces really does fail on the same audio.

The construction is the one in ``test_periodicity.py``, which is no accident:
this measurement is that analyzer's reading applied to a boundary.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from vinyl_process.analyzer import run_analysis
from vinyl_process.models.analysis import AnalysisDocument

SAMPLE_RATE = 44100
BEAT_SECONDS = 0.5
REVOLUTION_SECONDS = 1.3333
"""45 rpm — one of the two speeds the analyzer reports by default."""

MUSIC_END = 40.0
RUN_OUT_START = 64.0
"""Ground truth: the music, including its quiet outro, stops here."""
RUN_OUT_END = 88.0
LIFT_SECONDS = 6.0

TOLERANCE_SECONDS = 2.0
"""One `band_profile` frame is 0.2 s; the anchor is a 12 s window on a 4 s hop.
The refinement is what buys the precision, so this is loose enough to survive a
frame either way and far tighter than the 24-34 s errors it replaces."""


def _tick(samples: np.ndarray, at: float, amplitude: float, width: int) -> None:
    start = int(at * SAMPLE_RATE)
    if start + width <= samples.size:
        samples[start : start + width] += amplitude * np.hanning(width)


def _build(*, lift: bool, gap: bool = False, run_out: bool = True) -> np.ndarray:
    """A side, optionally with a needle lift, a mid-side gap, or no run-out."""
    end = RUN_OUT_END if run_out else RUN_OUT_START
    total = int((end + (LIFT_SECONDS if lift else 0.0)) * SAMPLE_RATE)
    t = np.arange(total) / SAMPLE_RATE
    rng = np.random.default_rng(20260821)

    # Surface noise the whole side long, louder in the run-out than under the
    # music, as an unmodulated groove is. Differencing white noise tilts it
    # towards the top of the band without pulling in a filter.
    samples = np.diff(rng.normal(0.0, 1.0, total + 1))
    samples[: int(RUN_OUT_START * SAMPLE_RATE)] *= 0.008
    samples[int(RUN_OUT_START * SAMPLE_RATE) : int(end * SAMPLE_RATE)] *= 0.018
    if lift:
        # The stylus is off the record: a floor tens of dB under the groove's,
        # which is the whole difficulty — it, not the run-out, is the quietest
        # thing in the trailing region.
        samples[int(end * SAMPLE_RATE) :] *= 4e-5

    # One tick per revolution, the whole side long — under the music too, where
    # the beat has to out-correlate it rather than merely appear in its absence.
    at = 0.0
    while at < end:
        _tick(samples, at, 0.10, 150)
        at += REVOLUTION_SECONDS

    # A kick on every beat, loud through the track and faint through the outro,
    # so the outro sits at the surface's level while still keeping time.
    at = 0.0
    while at < RUN_OUT_START:
        quiet = at >= MUSIC_END or (gap and 20.0 <= at < 26.0)
        _tick(samples, at, 0.18 if quiet else 0.55, 1200)
        at += BEAT_SECONDS

    body = slice(0, int(MUSIC_END * SAMPLE_RATE))
    samples[body] += 0.30 * np.sin(2 * np.pi * 180.0 * t[body])
    outro = slice(int(MUSIC_END * SAMPLE_RATE), int(RUN_OUT_START * SAMPLE_RATE))
    samples[outro] += 0.012 * np.sin(2 * np.pi * 180.0 * t[outro])
    if gap:
        # A quiet stretch in the middle of the side, at the run-out's own level.
        hole = slice(int(20.0 * SAMPLE_RATE), int(26.0 * SAMPLE_RATE))
        samples[hole] *= 0.05
    return samples


def _analyse(tmp_path: Path, name: str, **kwargs) -> AnalysisDocument:
    samples = _build(**kwargs)
    path = tmp_path / f"{name}.wav"
    sf.write(str(path), np.column_stack([samples, samples]), SAMPLE_RATE, subtype="PCM_24")
    return run_analysis(path, analyzers=["run_out", "boundaries"])


@pytest.fixture(scope="module")
def plain(tmp_path_factory: pytest.TempPathFactory) -> AnalysisDocument:
    return _analyse(tmp_path_factory.mktemp("run_out"), "plain", lift=False)


@pytest.fixture(scope="module")
def lifted(tmp_path_factory: pytest.TempPathFactory) -> AnalysisDocument:
    return _analyse(tmp_path_factory.mktemp("run_out"), "lifted", lift=True)


def test_the_run_out_is_found_where_it_was_built(plain: AnalysisDocument) -> None:
    section = plain.run_out
    assert section is not None
    assert section.start_sample is not None
    assert section.start_sample / SAMPLE_RATE == pytest.approx(RUN_OUT_START, abs=TOLERANCE_SECONDS)
    # The anchor is a window start, so it is at or before the answer, and the
    # refinement only ever moves later. Reported so the two bracket the truth.
    assert section.anchor_sample is not None
    assert section.anchor_sample <= section.start_sample
    assert len(section.run_out_band_levels_db) == len(plain.band_profile.bands)  # type: ignore[union-attr]


def test_the_needle_lift_does_not_move_the_answer(
    plain: AnalysisDocument, lifted: AnalysisDocument
) -> None:
    """The reference is a median of the tail, so the lift cannot set it.

    This is the regression. ``silence`` takes the *minimum* of its trailing
    region, which the lift owns, and that is what put the answer 27 s late on a
    real side.
    """
    assert plain.run_out is not None
    assert lifted.run_out is not None
    assert lifted.run_out.start_sample is not None
    assert lifted.run_out.start_sample / SAMPLE_RATE == pytest.approx(
        RUN_OUT_START, abs=TOLERANCE_SECONDS
    )
    assert plain.run_out.start_sample is not None
    moved = abs(lifted.run_out.start_sample - plain.run_out.start_sample) / SAMPLE_RATE
    assert moved <= 0.5, f"the lift moved the answer by {moved:.2f}s"


def test_the_lift_is_what_breaks_the_level_marker(
    plain: AnalysisDocument, lifted: AnalysisDocument
) -> None:
    """The other half: the marker this replaces really does fail here.

    Without a lift ``lead_out_start_sample`` is roughly right, because the
    trailing silence *is* the run-out. Add the lift and it jumps to the lift,
    since that is now where the level last crossed the threshold — measured on
    this fixture, 63.6 s becomes 88.1 s. A test that only showed the new field
    working would not show that the old one had to be replaced.
    """
    assert plain.boundaries is not None
    assert lifted.boundaries is not None
    without = plain.boundaries.lead_out_start_sample
    with_lift = lifted.boundaries.lead_out_start_sample
    assert without is not None
    assert with_lift is not None
    assert without / SAMPLE_RATE == pytest.approx(RUN_OUT_START, abs=2.0)
    assert with_lift / SAMPLE_RATE > RUN_OUT_END - 1.0, "the lift should have captured the marker"


def test_a_quiet_stretch_mid_side_is_not_the_run_out(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The anchor takes the *last* programme-looking window, not the first
    surface-looking one, so a quiet passage cannot end the side early."""
    document = _analyse(tmp_path_factory.mktemp("run_out"), "gap", lift=True, gap=True)
    assert document.run_out is not None
    assert document.run_out.start_sample is not None
    assert document.run_out.start_sample / SAMPLE_RATE > 30.0, "reported the mid-side gap"
    assert document.run_out.start_sample / SAMPLE_RATE == pytest.approx(
        RUN_OUT_START, abs=TOLERANCE_SECONDS + 2.0
    )


def test_a_side_that_ends_in_music_reports_nothing(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """``start_sample`` is ``None`` rather than the last sample: there is no
    run-out in the file, and inventing one would truncate the music."""
    document = _analyse(tmp_path_factory.mktemp("run_out"), "no-run-out", lift=False, run_out=False)
    assert document.run_out is not None
    assert document.run_out.start_sample is None
    assert document.run_out.meta.confidence == 0.0
