from itertools import islice

import numpy as np
import pytest

from sensor.config import Fault, SensorConfig
from sensor.simulator import Sample, get_fault_ranges, simulate

CFG = SensorConfig()
FAULT = CFG.default_fault()
RATE = CFG.sample_rate_hz


def _run(cfg: SensorConfig, seconds: float, faults=(FAULT,)) -> list[Sample]:
    return list(islice(simulate(cfg, faults), int(seconds * cfg.sample_rate_hz)))


def _peak_hz(accel: np.ndarray, sample_rate_hz: int) -> float:
    # Average 1 s Hann periodograms: one noisy FFT of a resonance can peak
    # a few Hz off, the average is stable.
    segment = sample_rate_hz
    frames = accel[: len(accel) // segment * segment].reshape(-1, segment)
    power = (np.abs(np.fft.rfft(frames * np.hanning(segment), axis=1)) ** 2).mean(0)
    freqs = np.fft.rfftfreq(segment, 1 / sample_rate_hz)
    return float(freqs[1:][np.argmax(power[1:])])


@pytest.fixture(scope="module")
def run_40s() -> list[Sample]:
    return _run(CFG, 40)


def test_same_seed_gives_identical_output():
    first = [s.accel for s in _run(CFG, 2)]
    second = [s.accel for s in _run(CFG, 2)]
    assert first == second


def test_different_seed_gives_different_output():
    seed_0 = [s.accel for s in _run(CFG, 1)]
    seed_1 = [s.accel for s in _run(SensorConfig(seed=1), 1)]
    assert seed_0 != seed_1


def test_fft_peak_baseline_and_fault(run_40s):
    accel = np.array([s.accel for s in run_40s])
    # Skip the first 2 s (start-up transient from rest) and the fault edges.
    baseline = accel[2 * RATE : 20 * RATE]
    faulted = accel[21 * RATE : 30 * RATE]
    assert _peak_hz(baseline, RATE) == pytest.approx(50, abs=2)
    assert _peak_hz(faulted, RATE) == pytest.approx(65, abs=2)


def test_default_fault_covers_exactly_20_to_30_s():
    assert get_fault_ranges(CFG, [FAULT]) == [(range(20 * RATE, 30 * RATE), FAULT)]


def test_no_faults_means_no_fault_ranges():
    assert get_fault_ranges(CFG, []) == []


def test_fault_range_is_exact_for_inexact_float_sums():
    # 0.2 + 0.1 == 0.30000000000000004: the sample at t = 0.3 must stay outside.
    fault = Fault(start=0.2, duration=0.1)
    assert get_fault_ranges(CFG, [fault]) == [(range(200, 300), fault)]


def test_adjacent_inexact_faults_are_not_an_overlap():
    simulate(CFG, [Fault(start=0.2, duration=0.1), Fault(start=0.3, duration=0.1)])


def test_fault_shorter_than_one_sample_is_rejected():
    with pytest.raises(ValueError, match="shorter than one sample"):
        simulate(CFG, [Fault(start=1.0, duration=0.0001)])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start": -1.0, "duration": 1.0},
        {"start": 0.0, "duration": 0.0},
        {"start": 0.0, "duration": 1.0, "freq_scale": 0.0},
        {"start": 0.0, "duration": 1.0, "damping_scale": -0.1},
    ],
)
def test_invalid_fault_is_rejected(kwargs):
    with pytest.raises(ValueError):
        Fault(**kwargs)


def test_overlapping_faults_are_rejected():
    faults = [Fault(start=5.0, duration=2.0), Fault(start=6.0, duration=2.0)]
    with pytest.raises(ValueError, match="overlapping"):
        simulate(CFG, faults)


def test_adjacent_faults_are_allowed():
    simulate(CFG, [Fault(start=5.0, duration=1.0), Fault(start=6.0, duration=1.0)])


def test_fault_too_fast_for_sample_rate_is_rejected():
    # 50 Hz × 4 → ωₙ·dt ≈ 1.26 at 1 kHz, above the stability margin.
    with pytest.raises(ValueError, match="sample rate"):
        simulate(CFG, [Fault(start=0.0, duration=1.0, freq_scale=4.0)])


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SENSOR_NATURAL_FREQ_HZ", "40")
    monkeypatch.setenv("SENSOR_SEED", "7")
    cfg = SensorConfig.from_env()
    assert cfg.natural_freq_hz == 40.0 and cfg.seed == 7 and cfg.sample_rate_hz == 1000
