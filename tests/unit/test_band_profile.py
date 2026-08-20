"""Band-profile accuracy: a filtered intro hiding inside a lead-in groove.

From side Y of a 2023 12" (Discogs 27040992). Both tracks open with a
band-limited element — the sort of telephone-EQ'd intro dub and house are built
on — several seconds before the bass entrance. `silence` put
`music_start_sample` at the *bass*, so 3.8 s of one intro and 7.3 s of the other
were cut off, and the person holding the record heard it.

Broadband level cannot find them, and the reason is worth stating precisely,
because the first version of this fixture got it backwards. Surface noise is not
"the quiet one" and not reliably "the bright one" either: its energy piles into
one band, on a played LP usually the lowest — unequalised groove noise rises about
3 dB/octave, then RIAA playback boosts the bass and cuts the treble — and that
band sets the broadband figure. On the record itself a clean run-out fell
monotonically, -71 dBFS in 40-150 Hz to -93 dBFS in 3-8 kHz. So an intro 30 dB up
in 400-1000 Hz moves `rms_profile` by a fraction of a dB while being unmissable
per band.

The fixture therefore builds a low-weighted surface, puts a mid-band intro inside
it, and asserts both halves: that the band profile finds the entrance, and, in
`test_the_fixture_still_poses_the_hard_case`, that the broadband envelope could
not have.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

from vinyl_process.analyzer import run_analysis
from vinyl_process.models.analysis import BandProfileSection

SAMPLE_RATE = 48000
LEAD_IN_SPAN = (0.0, 12.0)
INTRO_SPAN = (12.0, 20.0)
"""The intro: 600 Hz, band-limited, no bass and no top."""
PROGRAMME_SPAN = (20.0, 30.0)
"""The entrance proper: bass arrives and the level jumps."""

LOW_BAND = (40.0, 150.0)
MID_BAND = (400.0, 1000.0)
TOP_BAND = (3000.0, 8000.0)


@pytest.fixture(scope="module")
def recording(tmp_path_factory: pytest.TempPathFactory) -> Path:
    total = int(PROGRAMME_SPAN[1] * SAMPLE_RATE)
    time = np.arange(total) / SAMPLE_RATE
    rng = np.random.default_rng(20260820)

    # Surface noise the whole side long, weighted towards the low end as groove
    # noise after RIAA playback is: a low-passed bulk, plus a faint broadband
    # floor so the upper bands are not mathematically empty.
    white = rng.normal(0.0, 1.0, total)
    sos = butter(2, 200.0 / (SAMPLE_RATE / 2), btype="lowpass", output="sos")
    samples = 0.030 * np.asarray(sosfiltfilt(sos, white)) + 3e-5 * white

    def span(bounds: tuple[float, float]) -> slice:
        return slice(int(bounds[0] * SAMPLE_RATE), int(bounds[1] * SAMPLE_RATE))

    # The intro: one mid tone, inside 400-1000 Hz and nowhere near the bands
    # either side of it. Amplitude picked so the broadband level barely moves —
    # that is the trap, and the guard test below holds it shut.
    intro = span(INTRO_SPAN)
    samples[intro] += 0.001 * np.sin(2 * np.pi * 600.0 * time[intro])

    # The entrance: bass and mid together, plainly louder.
    programme = span(PROGRAMME_SPAN)
    samples[programme] += 0.20 * np.sin(2 * np.pi * 80.0 * time[programme])
    samples[programme] += 0.10 * np.sin(2 * np.pi * 600.0 * time[programme])

    path = tmp_path_factory.mktemp("band-profile") / "side-y.wav"
    sf.write(path, np.column_stack([samples, samples]), SAMPLE_RATE, subtype="PCM_24")
    return path


@pytest.fixture(scope="module")
def profile(recording: Path) -> BandProfileSection:
    section = run_analysis(recording, analyzers=["band_profile"]).band_profile
    assert section is not None
    return section


def _band(profile: BandProfileSection, edges: tuple[float, float]) -> np.ndarray:
    for band in profile.bands:
        if (band.low_hz, band.high_hz) == edges:
            return np.array(band.values_db)
    raise AssertionError(f"no band {edges} in {[(b.low_hz, b.high_hz) for b in profile.bands]}")


def _frames(profile: BandProfileSection, bounds: tuple[float, float]) -> slice:
    return slice(int(bounds[0] / profile.hop_seconds), int(bounds[1] / profile.hop_seconds))


def test_default_bands_are_reported_in_order(profile: BandProfileSection) -> None:
    edges = [(band.low_hz, band.high_hz) for band in profile.bands]
    assert edges == [
        (40.0, 150.0),
        (150.0, 400.0),
        (400.0, 1000.0),
        (1000.0, 3000.0),
        (3000.0, 8000.0),
    ]
    for band in profile.bands:
        assert len(band.values_db) == len(profile.bands[0].values_db)


def test_the_mid_band_finds_the_intro(profile: BandProfileSection) -> None:
    mid = _band(profile, MID_BAND)
    lead_in = mid[_frames(profile, LEAD_IN_SPAN)]
    intro = mid[_frames(profile, (INTRO_SPAN[0] + 0.4, INTRO_SPAN[1]))]
    assert intro.min() - lead_in.max() > 15.0


def test_the_intro_does_not_show_in_the_bands_around_it(profile: BandProfileSection) -> None:
    """A tone in one band must not be read as an entrance in another."""
    for edges in (LOW_BAND, TOP_BAND):
        values = _band(profile, edges)
        lead_in = values[_frames(profile, LEAD_IN_SPAN)]
        intro = values[_frames(profile, (INTRO_SPAN[0] + 0.4, INTRO_SPAN[1]))]
        assert abs(float(np.median(intro)) - float(np.median(lead_in))) < 3.0


def test_the_bass_entrance_shows_only_where_the_bass_is(profile: BandProfileSection) -> None:
    low = _band(profile, LOW_BAND)
    intro = low[_frames(profile, (INTRO_SPAN[0] + 0.4, INTRO_SPAN[1]))]
    programme = low[_frames(profile, (PROGRAMME_SPAN[0] + 0.4, PROGRAMME_SPAN[1]))]
    assert programme.min() - intro.max() > 20.0


def test_each_bands_floor_is_its_own(profile: BandProfileSection) -> None:
    """One floor for the whole recording would be the wrong figure per band: a
    played LP's surface is weighted low, so the bass band's floor sits tens of dB
    above the top band's, and a lift is only readable against its own band."""
    floors = {(b.low_hz, b.high_hz): b.floor_db for b in profile.bands}
    assert floors[LOW_BAND] - floors[TOP_BAND] > 15.0
    for edges, floor in floors.items():
        values = _band(profile, edges)
        assert floor == pytest.approx(float(np.percentile(values, 10.0)), abs=0.02)


def test_the_bands_of_a_frame_sum_to_its_total(
    recording: Path, profile: BandProfileSection
) -> None:
    """Parseval, with the Hann window's energy corrected for: the bands are a
    decomposition of the level, not five unrelated numbers, so a band can be
    compared against the total it belongs to."""
    samples, sample_rate = sf.read(recording, dtype="float64", always_2d=True)
    mono = samples.mean(axis=1)
    window = round(profile.window_seconds * sample_rate)
    frame = int(PROGRAMME_SPAN[0] / profile.hop_seconds) + 5
    start = round(frame * profile.hop_seconds * sample_rate)
    expected = float(np.mean(mono[start : start + window] ** 2))

    banded = sum(10 ** (_band(profile, e)[frame] / 10.0) for e in (LOW_BAND, MID_BAND))
    # Only the two bands the fixture puts programme in; the rest hold the surface,
    # which is far enough down to contribute nothing to the comparison.
    assert 10 * np.log10(banded) == pytest.approx(10 * np.log10(expected), abs=0.5)


def test_the_fixture_still_poses_the_hard_case(recording: Path) -> None:
    """Guard the premise, or the test above proves nothing.

    Two things have to hold. The broadband envelope must *not* separate intro
    from lead-in — that is what makes the band profile necessary. And the surface
    must be weighted towards the low end, as a played LP's is, so the fixture is
    not quietly testing the easy case of a bright surface over an empty bass band.
    """
    analysis = run_analysis(recording, analyzers=["rms_profile", "band_profile"])
    assert analysis.rms_profile is not None
    envelope = np.array(analysis.rms_profile.values_db)
    hop = analysis.rms_profile.hop_seconds
    lead_in = envelope[int(1.0 / hop) : int(LEAD_IN_SPAN[1] / hop)]
    intro = envelope[int((INTRO_SPAN[0] + 0.4) / hop) : int(INTRO_SPAN[1] / hop)]
    assert abs(float(np.median(intro)) - float(np.median(lead_in))) < 1.0

    profile = analysis.band_profile
    assert profile is not None
    surface = _frames(profile, LEAD_IN_SPAN)
    low = float(np.median(_band(profile, LOW_BAND)[surface]))
    mid = float(np.median(_band(profile, MID_BAND)[surface]))
    top = float(np.median(_band(profile, TOP_BAND)[surface]))
    assert low > mid > top
    assert low - top > 15.0
