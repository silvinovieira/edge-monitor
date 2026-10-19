"""Features computed on one window of samples."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Features:
    rms: float
    mean: float
    std: float
    peak_hz: float


def compute_features(window: np.ndarray, sample_rate_hz: int) -> Features:
    return Features(
        rms=float(np.sqrt(np.mean(window**2))),
        mean=float(np.mean(window)),
        std=float(np.std(window)),
        peak_hz=compute_peak_frequency(window, sample_rate_hz),
    )


def compute_peak_frequency(window: np.ndarray, sample_rate_hz: int) -> float:
    """Return the frequency with the most power, ignoring DC."""
    # Remove the mean first: the Hann taper would spread a DC offset (gravity,
    # sensor bias) into the lowest bins, where it could beat the real peak.
    centred = window - np.mean(window)
    # The Hann taper stops the window edges from smearing power across bins.
    power = np.abs(np.fft.rfft(centred * np.hanning(len(window)))) ** 2
    peak_bin = 1 + int(np.argmax(power[1:]))
    bin_width_hz = sample_rate_hz / len(window)
    return (peak_bin + _get_bin_offset(power, peak_bin)) * bin_width_hz


def _get_bin_offset(power: np.ndarray, peak_bin: int) -> float:
    """Locate the true peak between bins by fitting a parabola to three bins."""
    # Bins are ~1 Hz apart; without this the peak is only known to ±0.5 Hz.
    if peak_bin == len(power) - 1:
        return 0.0
    # Log power: a Hann peak is close to a parabola in log scale. The tiny
    # constant avoids log(0) for perfectly clean inputs.
    left, centre, right = np.log(power[peak_bin - 1 : peak_bin + 2] + 1e-20)
    curvature = left - 2 * centre + right
    return 0.0 if curvature == 0 else float(0.5 * (left - right) / curvature)
