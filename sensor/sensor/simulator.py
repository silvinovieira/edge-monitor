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
from itertools import islice, pairwise

import numpy as np

from sensor.config import Fault, SensorConfig, env_float

log = logging.getLogger(__name__)

# RK4 on an oscillator goes unstable near ωₙ·dt ≈ 2.8 and loses accuracy well
# before that; 1.0 keeps a wide margin (the defaults give 0.41 during a fault).
MAX_ANGULAR_FREQ_X_STEP = 1.0


@dataclass(frozen=True)
class Sample:
    t: float
    accel: float
    in_fault: bool


def _acceleration(
    displacement: float,
    velocity: float,
    forcing: float,
    angular_freq: float,
    damping_ratio: float,
) -> float:
    return (
        forcing
        - 2.0 * damping_ratio * angular_freq * velocity
        - angular_freq * angular_freq * displacement
    )


def _rk4_step(
    displacement: float,
    velocity: float,
    forcing: float,
    angular_freq: float,
    damping_ratio: float,
    step_s: float,
) -> tuple[float, float]:
    # The forcing is held constant across the four stages: it is a zero-order-hold
    # input, so drawing it per stage would change its effective variance.
    def slopes(at_displacement: float, at_velocity: float) -> tuple[float, float]:
        return at_velocity, _acceleration(
            at_displacement, at_velocity, forcing, angular_freq, damping_ratio
        )

    d_disp1, d_vel1 = slopes(displacement, velocity)
    d_disp2, d_vel2 = slopes(
        displacement + 0.5 * step_s * d_disp1, velocity + 0.5 * step_s * d_vel1
    )
    d_disp3, d_vel3 = slopes(
        displacement + 0.5 * step_s * d_disp2, velocity + 0.5 * step_s * d_vel2
    )
    d_disp4, d_vel4 = slopes(
        displacement + step_s * d_disp3, velocity + step_s * d_vel3
    )
    displacement += step_s / 6.0 * (d_disp1 + 2.0 * d_disp2 + 2.0 * d_disp3 + d_disp4)
    velocity += step_s / 6.0 * (d_vel1 + 2.0 * d_vel2 + 2.0 * d_vel3 + d_vel4)
    return displacement, velocity


@dataclass(frozen=True)
class _FaultWindow:
    """A fault mapped to sample indices: active for first <= index < end."""

    first: int
    end: int
    fault: Fault


def _to_windows(cfg: SensorConfig, faults: Sequence[Fault]) -> tuple[_FaultWindow, ...]:
    # Compare integer sample indices, never float times: 0.2 + 0.1 is
    # 0.30000000000000004, which would wrongly put the sample at t = 0.3 inside.
    # Boundaries between samples round to the nearest sample.
    rate = cfg.sample_rate_hz
    return tuple(
        _FaultWindow(round(f.start * rate), round(f.end * rate), f) for f in faults
    )


def _validate(cfg: SensorConfig, windows: Sequence[_FaultWindow]) -> None:
    max_freq_scale = max([1.0, *(w.fault.freq_scale for w in windows)])
    angular_freq = 2.0 * math.pi * cfg.natural_freq_hz * max_freq_scale
    if angular_freq / cfg.sample_rate_hz > MAX_ANGULAR_FREQ_X_STEP:
        raise ValueError("sample rate too low for the (faulted) natural frequency")
    for window in windows:
        if window.end <= window.first:
            raise ValueError(f"fault shorter than one sample: {window.fault}")
    ordered = sorted(windows, key=lambda w: w.first)
    for earlier, later in pairwise(ordered):
        if later.first < earlier.end:
            raise ValueError(f"overlapping faults: {earlier.fault} and {later.fault}")


def _active_fault(windows: Sequence[_FaultWindow], sample_index: int) -> Fault | None:
    for window in windows:
        if window.first <= sample_index < window.end:
            return window.fault
    return None


def simulate(cfg: SensorConfig, faults: Sequence[Fault] = ()) -> Iterator[Sample]:
    """Yield samples forever, one at a time; the caller decides when to stop."""
    # Validate here, not in the generator body, so bad input fails at the call
    # instead of on the first next().
    windows = _to_windows(cfg, faults)
    _validate(cfg, windows)
    return _generate(cfg, windows)


def _generate(cfg: SensorConfig, windows: tuple[_FaultWindow, ...]) -> Iterator[Sample]:
    noise = np.random.default_rng(cfg.seed)
    step_s = 1.0 / cfg.sample_rate_hz
    natural_angular_freq = 2.0 * math.pi * cfg.natural_freq_hz
    displacement = velocity = 0.0
    sample_index = 0
    while True:
        # Time from the integer index, so it never drifts from accumulating step_s.
        t = sample_index / cfg.sample_rate_hz
        active_fault = _active_fault(windows, sample_index)
        angular_freq, damping_ratio = natural_angular_freq, cfg.damping_ratio
        if active_fault is not None:
            angular_freq *= active_fault.freq_scale
            damping_ratio *= active_fault.damping_scale
        forcing = float(noise.normal(0.0, cfg.noise_std))
        yield Sample(
            t=t,
            accel=_acceleration(
                displacement, velocity, forcing, angular_freq, damping_ratio
            ),
            in_fault=active_fault is not None,
        )
        displacement, velocity = _rk4_step(
            displacement, velocity, forcing, angular_freq, damping_ratio, step_s
        )
        sample_index += 1


def main() -> None:
    """Log the samples in [SENSOR_PRINT_FROM, + SENSOR_PRINT_SECONDS) seconds."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = SensorConfig.from_env()
    # Sample indices, rounded like fault boundaries, so the printed range is exact.
    first = round(env_float("SENSOR_PRINT_FROM", 0.0) * cfg.sample_rate_hz)
    count = round(env_float("SENSOR_PRINT_SECONDS", 1.0) * cfg.sample_rate_hz)
    samples = simulate(cfg, [cfg.default_fault()])
    for sample in islice(samples, first, first + count):
        log.info(sample)


if __name__ == "__main__":
    main()
