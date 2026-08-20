"""Periodicity accuracy: two equally quiet stretches, one music, one surface.

This is the case that motivated the analyzer, from side Y of a 2023 12". The
track ended in a dub outro so quiet it sat at the surface-noise level, and the
level threshold duly called it the run-out groove — ``lead_out_start_sample`` was
22 s early, and cutting there would have chopped the end off the track. Nothing
about level or spectrum separates a quiet outro from a run-out groove. What does
is that the outro keeps the beat while the run-out repeats once per revolution.

So the fixture puts a quiet outro and a run-out groove within a couple of dB of
each other and asserts both halves: that periodicity tells them apart, and, in
``test_the_fixture_still_poses_the_hard_case``, that level could not have.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from vinyl_process.analyzer import run_analysis
from vinyl_process.models.analysis import PeriodicitySection, PeriodicityWindow

SAMPLE_RATE = 44100
BEAT_SECONDS = 0.5
REVOLUTION_SECONDS = 1.3333
"""45 rpm — one of the two speeds the analyzer reports by default."""

MUSIC_SPAN = (0.0, 40.0)
OUTRO_SPAN = (40.0, 64.0)
"""Still the track: quiet, but on the beat."""
RUNOUT_SPAN = (64.0, 88.0)
"""No longer the track: the same level, but on the revolution."""


def _tick(samples: np.ndarray, at: float, amplitude: float, width: int) -> None:
    start = int(at * SAMPLE_RATE)
    if start + width <= samples.size:
        samples[start : start + width] += amplitude * np.hanning(width)


@pytest.fixture(scope="module")
def recording(tmp_path_factory: pytest.TempPathFactory) -> Path:
    total = int(RUNOUT_SPAN[1] * SAMPLE_RATE)
    t = np.arange(total) / SAMPLE_RATE
    rng = np.random.default_rng(20260820)

    # Surface noise the whole side long, louder in the run-out than under the
    # music, as an unmodulated groove is. Differencing white noise tilts it
    # towards the top of the band without pulling in a filter.
    samples = np.diff(rng.normal(0.0, 1.0, total + 1))
    samples[: int(RUNOUT_SPAN[0] * SAMPLE_RATE)] *= 0.008
    samples[int(RUNOUT_SPAN[0] * SAMPLE_RATE) :] *= 0.018

    # One tick per revolution, the whole side long — under the music too, where
    # the beat has to out-correlate it rather than merely appear in its absence.
    at = 0.0
    while at < RUNOUT_SPAN[1]:
        _tick(samples, at, 0.10, 150)
        at += REVOLUTION_SECONDS

    # A kick on every beat, loud through the track and faint through the outro.
    at = 0.0
    while at < OUTRO_SPAN[1]:
        _tick(samples, at, 0.55 if at < MUSIC_SPAN[1] else 0.18, 1200)
        at += BEAT_SECONDS
    body = slice(0, int(MUSIC_SPAN[1] * SAMPLE_RATE))
    samples[body] += 0.30 * np.sin(2 * np.pi * 180.0 * t[body])
    outro = slice(int(OUTRO_SPAN[0] * SAMPLE_RATE), int(OUTRO_SPAN[1] * SAMPLE_RATE))
    samples[outro] += 0.012 * np.sin(2 * np.pi * 180.0 * t[outro])

    path = tmp_path_factory.mktemp("periodicity") / "side.wav"
    sf.write(str(path), np.column_stack([samples, samples]), SAMPLE_RATE, subtype="PCM_24")
    return path


@pytest.fixture(scope="module")
def section(recording: Path) -> PeriodicitySection:
    measured = run_analysis(recording, analyzers=["periodicity"]).periodicity
    assert measured is not None
    return measured


def _within(section: PeriodicitySection, span: tuple[float, float]) -> list[PeriodicityWindow]:
    lo, hi = (int(edge * SAMPLE_RATE) for edge in span)
    inside = [w for w in section.windows if w.start_sample >= lo and w.end_sample <= hi]
    assert inside, f"no probe window lies wholly inside {span}"
    return inside


def _revolution_share(window: PeriodicityWindow) -> float:
    """Correlation at 45 rpm as a fraction of the window's own strongest peak."""
    for entry in window.revolution:
        if entry.period_seconds == pytest.approx(REVOLUTION_SECONDS, abs=0.01):
            return entry.r / max(window.peaks[0].r, 1e-9)
    raise AssertionError("no 45 rpm revolution entry")


def test_the_beat_is_measured_over_the_programme(section: PeriodicitySection) -> None:
    assert section.programme_period_seconds is not None
    # The beat or a multiple of it — never the revolution, which is what a
    # whole-side estimate would drift towards on a side with a long run-out.
    ratio = section.programme_period_seconds / BEAT_SECONDS
    assert ratio == pytest.approx(round(ratio), abs=0.05)
    assert section.programme_peak_prominence is not None
    assert section.programme_peak_prominence > 0.1


def test_the_quiet_outro_still_reads_as_music(section: PeriodicitySection) -> None:
    for window in _within(section, OUTRO_SPAN):
        top = window.peaks[0]
        beats = top.period_seconds / BEAT_SECONDS
        assert beats == pytest.approx(round(beats), abs=0.06), window
        assert _revolution_share(window) < 0.5, window


def test_the_run_out_reads_as_surface(section: PeriodicitySection) -> None:
    for window in _within(section, RUNOUT_SPAN):
        assert _revolution_share(window) > 0.85, window
        assert window.peaks[0].period_seconds == pytest.approx(REVOLUTION_SECONDS, abs=0.02), window


def test_the_beat_wins_under_the_music_where_the_tick_is_masked(
    section: PeriodicitySection,
) -> None:
    for window in _within(section, MUSIC_SPAN):
        assert _revolution_share(window) < 0.5, window


def test_the_fixture_still_poses_the_hard_case(recording: Path) -> None:
    """The premise, so the tests above cannot start passing for the wrong reason
    after a later edit quietens the run-out or loudens the outro."""
    samples, _ = sf.read(str(recording), dtype="float64", always_2d=True)
    mono = samples.mean(axis=1)

    def rms(edges: tuple[float, float]) -> float:
        lo, hi = (int(edge * SAMPLE_RATE) for edge in edges)
        return float(np.sqrt(np.mean(np.asarray(mono[lo:hi]) ** 2)))

    difference_db = 20 * np.log10(rms(OUTRO_SPAN) / rms(RUNOUT_SPAN))
    assert abs(difference_db) < 3.0, (
        f"outro and run-out are {difference_db:.1f} dB apart; "
        "a level threshold would separate them and the test would prove nothing"
    )
