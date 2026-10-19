import numpy as np
import pytest

from processing.features import compute_features, compute_peak_frequency

RATE = 1000


def _make_sine(freq_hz: float, amplitude: float = 1.0, size: int = 1024):
    return amplitude * np.sin(2 * np.pi * freq_hz * np.arange(size) / RATE)


def test_features_of_a_pure_sine():
    features = compute_features(_make_sine(50.0, amplitude=2.0), RATE)
    assert features.rms == pytest.approx(2 / np.sqrt(2), rel=0.01)
    assert features.mean == pytest.approx(0.0, abs=0.01)
    assert features.std == pytest.approx(features.rms, rel=0.01)
    assert features.peak_hz == pytest.approx(50.0, abs=0.1)


@pytest.mark.parametrize("freq_hz", [12.3, 50.0, 65.0, 137.7])
def test_peak_frequency_is_found_between_bins(freq_hz):
    # Bins are 1000 / 1024 ≈ 0.98 Hz apart; interpolation should beat that.
    assert compute_peak_frequency(_make_sine(freq_hz), RATE) == pytest.approx(
        freq_hz, abs=0.1
    )


def test_peak_frequency_ignores_dc_offset():
    window = 10.0 + _make_sine(40.0)
    assert compute_peak_frequency(window, RATE) == pytest.approx(40.0, abs=0.1)
