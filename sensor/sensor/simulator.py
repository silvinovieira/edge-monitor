"""Noise-driven damped harmonic oscillator with injectable faults.

    x'' + 2·ζ·ωₙ·x' + ωₙ²·x = F(t),   F ~ N(0, noise_std)

x is displacement, ωₙ the angular frequency (rad/s), ζ the damping ratio and F the
forcing. The state [displacement, velocity] is integrated with RK4. Each sample is
the acceleration an accelerometer reads, a = F − 2·ζ·ωₙ·v − ωₙ²·x, so it contains
the white forcing term itself on top of the resonant response; that is intended.
"""

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from sensor.config import Fault, SensorConfig

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


def _validate_faults(cfg: SensorConfig, faults: Sequence[Fault]) -> None:
    max_freq_scale = max([1.0, *(f.freq_scale for f in faults)])
    angular_freq = 2.0 * math.pi * cfg.natural_freq_hz * max_freq_scale
    if angular_freq / cfg.sample_rate_hz > MAX_ANGULAR_FREQ_X_STEP:
        raise ValueError("sample rate too low for the (faulted) natural frequency")
    ordered = sorted(faults, key=lambda f: f.start)
    for earlier, later in pairwise(ordered):
        if later.start < earlier.end:
            raise ValueError(f"overlapping faults: {earlier} and {later}")


def _active_fault(faults: Sequence[Fault], t: float) -> Fault | None:
    for fault in faults:
        if fault.contains(t):
            return fault
    return None


def simulate(cfg: SensorConfig, faults: Sequence[Fault] = ()) -> Iterator[Sample]:
    """Yield samples forever, one at a time; the caller decides when to stop."""
    # Validate here, not in the generator body, so bad input fails at the call
    # instead of on the first next().
    _validate_faults(cfg, faults)
    return _generate(cfg, tuple(faults))


def _generate(cfg: SensorConfig, faults: tuple[Fault, ...]) -> Iterator[Sample]:
    noise = np.random.default_rng(cfg.seed)
    step_s = 1.0 / cfg.sample_rate_hz
    natural_angular_freq = 2.0 * math.pi * cfg.natural_freq_hz
    displacement = velocity = 0.0
    sample_index = 0
    while True:
        # Time from the integer index, so it never drifts from accumulating step_s.
        t = sample_index / cfg.sample_rate_hz
        active_fault = _active_fault(faults, t)
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
