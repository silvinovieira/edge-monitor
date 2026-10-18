from itertools import islice

import numpy as np
import pytest

from sensor.config import SensorConfig
from sensor.simulator import Fault, simulate

CFG = SensorConfig()
FAULT = CFG.default_fault()


def _run(cfg: SensorConfig, seconds: float, faults=(FAULT,)) -> list:
    return list(islice(simulate(cfg, faults), int(seconds * cfg.fs)))


def _peak_hz(accel: np.ndarray, fs: int) -> float:
    # Average 1 s Hann periodograms: one noisy FFT of a resonance can peak
    # a few Hz off, the average is stable.
    seg = fs
    frames = accel[: len(accel) // seg * seg].reshape(-1, seg)
    spectrum = (np.abs(np.fft.rfft(frames * np.hanning(seg), axis=1)) ** 2).mean(0)
    freqs = np.fft.rfftfreq(seg, 1 / fs)
    return float(freqs[1:][np.argmax(spectrum[1:])])


@pytest.fixture(scope="module")
def run_40s() -> list:
    return _run(CFG, 40)


def test_same_seed_gives_identical_output():
    a = [s.accel for s in _run(CFG, 2)]
    b = [s.accel for s in _run(CFG, 2)]
    assert a == b


def test_different_seed_gives_different_output():
    a = [s.accel for s in _run(CFG, 1)]
    b = [s.accel for s in _run(SensorConfig(seed=1), 1)]
    assert a != b


def test_fft_peak_baseline_and_fault(run_40s):
    accel = np.array([s.accel for s in run_40s])
    # Skip the first 2 s (start-up transient from rest) and the fault edges.
    baseline = accel[2 * CFG.fs : 20 * CFG.fs]
    fault = accel[21 * CFG.fs : 30 * CFG.fs]
    assert _peak_hz(baseline, CFG.fs) == pytest.approx(50, abs=2)
    assert _peak_hz(fault, CFG.fs) == pytest.approx(65, abs=2)


def test_in_fault_exactly_in_window(run_40s):
    for s in run_40s:
        assert s.in_fault == (20.0 <= s.t < 30.0), s.t
    flags = [s.in_fault for s in run_40s]
    assert flags.index(True) == 20 * CFG.fs
    assert len(flags) - flags[::-1].index(True) == 30 * CFG.fs


def test_no_faults_means_never_in_fault():
    assert not any(s.in_fault for s in _run(CFG, 1, faults=()))


def test_fault_contains_is_half_open():
    f = Fault(start=1.0, duration=2.0)
    assert f.contains(1.0) and f.contains(2.999) and not f.contains(3.0)


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SENSOR_F_N_HZ", "40")
    monkeypatch.setenv("SENSOR_SEED", "7")
    cfg = SensorConfig.from_env()
    assert cfg.f_n_hz == 40.0 and cfg.seed == 7 and cfg.fs == 1000
