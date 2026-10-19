"""Noise-driven damped harmonic oscillator with injectable faults.

    x'' + 2·ζ·ωₙ·x' + ωₙ²·x = F(t),   F ~ N(0, noise_std)

x is displacement, ωₙ the angular frequency (rad/s), ζ the damping ratio and F the
forcing. The state [displacement, velocity] is integrated with RK4. Each sample is
the acceleration an accelerometer reads, a = F − 2·ζ·ωₙ·v − ωₙ²·x, so it contains
the white forcing term itself on top of the resonant response; that is intended.
"""

import logging
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import count, islice, pairwise

import numpy as np

from sensor.config import Fault, SensorConfig

log = logging.getLogger(__name__)

# RK4 on an oscillator goes unstable near ωₙ·dt ≈ 2.8 and loses accuracy well
# before that; 1.0 keeps a wide margin (the defaults give 0.41 during a fault).
MAX_RADIANS_PER_STEP = 1.0


@dataclass(frozen=True)
class Sample:
    t: float
    accel: float


def _get_acceleration(
    state: np.ndarray, forcing: float, angular_freq: float, damping_ratio: float
) -> float:
    displacement, velocity = state
    return float(
        forcing
        - 2.0 * damping_ratio * angular_freq * velocity
        - angular_freq**2 * displacement
    )


def _get_derivative(state: np.ndarray, *params: float) -> np.ndarray:
    return np.array([state[1], _get_acceleration(state, *params)])


def _step_rk4(state: np.ndarray, step_s: float, *params: float) -> np.ndarray:
    # The forcing in params is held constant across the four stages: it is a
    # zero-order-hold input, so drawing it per stage would change its variance.
    k1 = _get_derivative(state, *params)
    k2 = _get_derivative(state + step_s / 2 * k1, *params)
    k3 = _get_derivative(state + step_s / 2 * k2, *params)
    k4 = _get_derivative(state + step_s * k3, *params)
    return state + step_s / 6 * (k1 + 2 * k2 + 2 * k3 + k4)


def get_fault_ranges(
    cfg: SensorConfig, faults: Sequence[Fault]
) -> list[tuple[range, Fault]]:
    """Map each fault to the sample indices it covers, sorted and validated.

    This is also the ground truth: sample i is faulted exactly when i is in one of
    the ranges, because the simulator applies faults from these same ranges.
    """
    # Integer sample indices, never float times: 0.2 + 0.1 is 0.30000000000000004,
    # which would wrongly put the sample at t = 0.3 inside.
    rate = cfg.sample_rate_hz
    fault_ranges = sorted(
        ((range(round(f.start * rate), round(f.end * rate)), f) for f in faults),
        key=lambda pair: pair[0].start,
    )
    for samples, fault in fault_ranges:
        if not samples:
            raise ValueError(f"fault shorter than one sample: {fault}")
    for (earlier, first), (later, second) in pairwise(fault_ranges):
        if later.start < earlier.stop:
            raise ValueError(f"overlapping faults: {first} and {second}")
    return fault_ranges


def _check_sample_rate(cfg: SensorConfig, faults: Sequence[Fault]) -> None:
    fastest_scale = max([1.0, *(f.freq_scale for f in faults)])
    angular_freq = 2.0 * math.pi * cfg.natural_freq_hz * fastest_scale
    if angular_freq / cfg.sample_rate_hz > MAX_RADIANS_PER_STEP:
        raise ValueError("sample rate too low for the (faulted) natural frequency")


def _find_active_fault(
    fault_ranges: list[tuple[range, Fault]], index: int
) -> Fault | None:
    return next((fault for samples, fault in fault_ranges if index in samples), None)


def simulate(cfg: SensorConfig, faults: Sequence[Fault] = ()) -> Iterator[Sample]:
    """Yield samples forever, one at a time; the caller decides when to stop."""
    # Validate here, not in the generator, so bad input fails at the call
    # instead of on the first next().
    _check_sample_rate(cfg, faults)
    return _generate_samples(cfg, get_fault_ranges(cfg, faults))


def _generate_samples(
    cfg: SensorConfig, fault_ranges: list[tuple[range, Fault]]
) -> Iterator[Sample]:
    noise = np.random.default_rng(cfg.seed)
    step_s = 1.0 / cfg.sample_rate_hz
    state = np.zeros(2)  # [displacement, velocity], starting at rest
    for index in count():
        fault = _find_active_fault(fault_ranges, index)
        freq_scale = fault.freq_scale if fault else 1.0
        damping_scale = fault.damping_scale if fault else 1.0
        angular_freq = 2.0 * math.pi * cfg.natural_freq_hz * freq_scale
        damping_ratio = cfg.damping_ratio * damping_scale
        forcing = float(noise.normal(0.0, cfg.noise_std))
        params = (forcing, angular_freq, damping_ratio)
        # Time from the integer index, so it never drifts from summing step_s.
        yield Sample(
            t=index / cfg.sample_rate_hz,
            accel=_get_acceleration(state, *params),
        )
        state = _step_rk4(state, step_s, *params)


def main() -> None:
    """Log the first second of samples, with the default fault."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = SensorConfig.from_env()
    for sample in islice(simulate(cfg, [cfg.default_fault()]), cfg.sample_rate_hz):
        log.info(sample)


if __name__ == "__main__":
    main()
