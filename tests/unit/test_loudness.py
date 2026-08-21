"""EBU Tech 3341 conformance for the K-weighted loudness measurement.

This is the one measurement in this repository with an **external** correctness
oracle. Everywhere else the analyzer is tested for accuracy against ground truth
this project synthesised, and the DSP for exactness against itself — because
ranking one algorithm against damage the same hand injected is circular. Loudness
is different: ITU-R BS.1770 defines the arithmetic and EBU Tech 3341 publishes the
readings a compliant implementation must produce, with tolerances.

``docs/architecture.md`` said `album_lufs` must not ship without these, so here
they are. The test signals are *described* by Tech 3341 rather than supplied as
files, which is what lets them be synthesised in-test — no binary fixtures, the
same rule as everywhere else.

Not covered, and deliberately: cases 7 and 8 need "authentic programme" audio that
cannot be synthesised, and cases 9 to 14 test momentary and short-term *meters*.
There is no meter here — one integrated figure per album — so those cases describe
a device this project does not implement.
"""

from __future__ import annotations

import numpy as np
import pytest

from vinyl_process.signal_ops import (
    k_weighting_coefficients,
    loudness_lufs,
)

# ITU-R BS.1770-5, Tables 1 and 2: the coefficients for 48 kHz, verbatim.
BS1770_STAGE1_B = [1.53512485958697, -2.69169618940638, 1.19839281085285]
BS1770_STAGE1_A = [1.0, -1.69065929318241, 0.73248077421585]
BS1770_STAGE2_B = [1.0, -2.0, 1.0]
BS1770_STAGE2_A = [1.0, -1.99004745483398, 0.99007225036621]

TOLERANCE_LU = 0.1
"""Tech 3341's stated tolerance on every case used here: "±0.1 LUFS"."""

RATES = (44100, 48000)


def sine(sample_rate: int, seconds: float, dbfs: float, channels: int = 2) -> np.ndarray:
    """Tech 3341's building block: 1000 Hz applied in phase to every channel, at a
    stated **per-channel peak level**."""
    frames = round(seconds * sample_rate)
    t = np.arange(frames) / sample_rate
    wave = (10.0 ** (dbfs / 20.0)) * np.sin(2 * np.pi * 1000.0 * t)
    return np.tile(wave[:, None], (1, channels))


def segments(sample_rate: int, spec: list[tuple[float, float]]) -> np.ndarray:
    return np.vstack([sine(sample_rate, seconds, dbfs) for seconds, dbfs in spec])


def test_the_derivation_reproduces_the_standards_tabulated_48khz_coefficients() -> None:
    """BS.1770 tabulates 48 kHz only and requires other rates be re-derived to give
    "the same frequency response that the specified filter provides at 48 kHz".

    So the analogue prototype in ``signal_ops`` is only trustworthy insofar as it
    lands on the published table when asked for 48 kHz. It does, to machine
    precision — which is the evidence that the coefficients were derived and not
    remembered.
    """
    (stage1_b, stage1_a), (stage2_b, stage2_a) = k_weighting_coefficients(48000)
    for got, expected in (
        (stage1_b, BS1770_STAGE1_B),
        (stage1_a, BS1770_STAGE1_A),
        (stage2_b, BS1770_STAGE2_B),
        (stage2_a, BS1770_STAGE2_A),
    ):
        assert got == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("sample_rate", RATES)
def test_the_standards_own_reference_reading(sample_rate: int) -> None:
    """BS.1770: "If a 0 dB FS, 1 kHz (997 Hz to be exact) sine wave is applied to
    the left, centre, or right channel input, the indicated loudness will equal
    −3.01 LKFS." """
    frames = round(10.0 * sample_rate)
    t = np.arange(frames) / sample_rate
    one_channel = np.sin(2 * np.pi * 997.0 * t)[:, None]
    assert loudness_lufs(one_channel, sample_rate) == pytest.approx(-3.01, abs=TOLERANCE_LU)


@pytest.mark.parametrize("sample_rate", RATES)
def test_case_1_stereo_sine_at_minus_23(sample_rate: int) -> None:
    """ "Stereo sine wave, 1000 Hz, −23.0 dBFS (per-channel peak level); signal
    applied in phase to both channels simultaneous; 20 s duration" → I = −23.0.

    The case that pins the channel **sum**: averaging the two channels instead of
    summing them would read −26, and the −0.691 offset would no longer cancel the
    K-weighting's gain at 1 kHz.
    """
    got = loudness_lufs(sine(sample_rate, 20.0, -23.0), sample_rate)
    assert got == pytest.approx(-23.0, abs=TOLERANCE_LU)


@pytest.mark.parametrize("sample_rate", RATES)
def test_case_2_stereo_sine_at_minus_33(sample_rate: int) -> None:
    """ "As #1 at −33.0 dBFS" → I = −33.0. Linearity."""
    got = loudness_lufs(sine(sample_rate, 20.0, -33.0), sample_rate)
    assert got == pytest.approx(-33.0, abs=TOLERANCE_LU)


@pytest.mark.parametrize("sample_rate", RATES)
def test_case_3_the_relative_gate_drops_the_quiet_ends(sample_rate: int) -> None:
    """ "10 s at −36.0 dBFS; 60 s at −23.0 dBFS; 10 s at −36.0 dBFS" → I = −23.0.

    Only the relative gate can produce this: the −36 dB segments are far above the
    absolute gate, so an implementation with the absolute gate alone reads low.
    """
    audio = segments(sample_rate, [(10.0, -36.0), (60.0, -23.0), (10.0, -36.0)])
    assert loudness_lufs(audio, sample_rate) == pytest.approx(-23.0, abs=TOLERANCE_LU)


@pytest.mark.parametrize("sample_rate", RATES)
def test_case_4_the_absolute_gate_drops_the_silence(sample_rate: int) -> None:
    """ "10 s at −72.0; 10 s at −36.0; 60 s at −23.0; 10 s at −36.0; 10 s at −72.0"
    → I = −23.0. The −72 dB segments sit under the absolute gate at −70."""
    audio = segments(
        sample_rate,
        [(10.0, -72.0), (10.0, -36.0), (60.0, -23.0), (10.0, -36.0), (10.0, -72.0)],
    )
    assert loudness_lufs(audio, sample_rate) == pytest.approx(-23.0, abs=TOLERANCE_LU)


@pytest.mark.parametrize("sample_rate", RATES)
def test_case_5_the_relative_gate_sits_where_the_standard_puts_it(sample_rate: int) -> None:
    """ "20 s at −26.0 dBFS; 20.1 s at −20.0 dBFS; 20 s at −26.0 dBFS" → I = −23.0.

    The sharpest of the five: the quiet segments are only 6 dB down, so they fall
    on the far side of the relative gate by a margin that a gate placed a decibel
    away would get wrong. The odd 20.1 s is Tech 3341's, not a typo.
    """
    audio = segments(sample_rate, [(20.0, -26.0), (20.1, -20.0), (20.0, -26.0)])
    assert loudness_lufs(audio, sample_rate) == pytest.approx(-23.0, abs=TOLERANCE_LU)


@pytest.mark.parametrize("sample_rate", RATES)
def test_case_6_the_channel_weights(sample_rate: int) -> None:
    """ "5.0 channel sine wave, 1000 Hz, 20 s duration … −28.0 dBFS in L and R,
    −24.0 dBFS in C, −30.0 dBFS in Ls and Rs" → I = −23.0.

    The only case that can catch a wrong channel weight: in stereo every weight is
    1.0, so nothing distinguishes a correct table from a table of ones. A vinyl
    transfer is never 5.0 — this runs so the formula is proven, not because the
    layout is expected.
    """
    frames = round(20.0 * sample_rate)
    t = np.arange(frames) / sample_rate

    def channel(dbfs: float) -> np.ndarray:
        return (10.0 ** (dbfs / 20.0)) * np.sin(2 * np.pi * 1000.0 * t)

    five = np.column_stack(
        [channel(-28.0), channel(-28.0), channel(-24.0), channel(-30.0), channel(-30.0)]
    )
    assert loudness_lufs(five, sample_rate) == pytest.approx(-23.0, abs=TOLERANCE_LU)


def test_loudness_of_material_too_short_for_a_gating_block() -> None:
    """BS.1770 drops incomplete blocks, so 100 ms has nothing to measure at all."""
    short = sine(48000, 0.1, -23.0)
    assert loudness_lufs(short, 48000) < -100.0


def test_lufs_and_gated_rms_differ_by_the_k_weighting() -> None:
    """The reason ``album_lufs`` is a separate mode and not a fix to the other one.

    On a bright signal the K-weighting's shelf raises the reading; on a bass-heavy
    one its high-pass lowers it. Same gates, same block geometry, different
    quantity — which is exactly ``adr/0008``'s argument, applied again.
    """
    from vinyl_process.signal_ops import amplitude_to_db, gated_rms

    frames = round(20.0 * 48000)
    t = np.arange(frames) / 48000

    def stereo(hz: float) -> np.ndarray:
        wave = 0.1 * np.sin(2 * np.pi * hz * t)
        return np.tile(wave[:, None], (1, 2))

    def gap(hz: float) -> float:
        audio = stereo(hz)
        return loudness_lufs(audio, 48000) - float(amplitude_to_db(gated_rms(audio, 48000)))

    # Calibrate on 997 Hz rather than on arithmetic: the Recommendation states that
    # the -0.691 offset "cancels out the K-weighting gain for 997 Hz", so whatever
    # the gap is there is the *unweighted* difference between the two measurements
    # (a stereo sum against a channel average). Everything else is the filter.
    reference = gap(997.0)
    assert gap(8000.0) - reference > 1.0, "the shelf must raise a bright signal"
    assert gap(40.0) - reference < -3.0, "the RLB high-pass must lower a subsonic one"
