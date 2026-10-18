"""Noise-driven damped harmonic oscillator with injectable faults.

    x'' + 2*zeta*omega*x' + omega**2 * x = F(t),   F ~ N(0, noise_std)

Integrated with RK4 on the state [x, v]. Each sample is the acceleration an
accelerometer would read: a = F - 2*zeta*omega*v - omega**2 * x.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sensor.config import SensorConfig


@dataclass(frozen=True)
class Sample:
    t: float
    accel: float
    in_fault: bool


@dataclass(frozen=True)
class Fault:
    """Scales omega and zeta during the half-open window [start, start + duration)."""

    start: float
    duration: float
    omega_scale: float = 1.0
    zeta_scale: float = 1.0

    @property
    def end(self) -> float:
        return self.start + self.duration

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end


def _accel(x: float, v: float, force: float, omega: float, zeta: float) -> float:
    return force - 2.0 * zeta * omega * v - omega * omega * x


def _rk4_step(
    x: float, v: float, force: float, omega: float, zeta: float, dt: float
) -> tuple[float, float]:
    # F is held constant across the four stages: the noise is a zero-order-hold
    # input, so drawing it per stage would change its effective variance.
    k1x, k1v = v, _accel(x, v, force, omega, zeta)
    k2x = v + 0.5 * dt * k1v
    k2v = _accel(x + 0.5 * dt * k1x, k2x, force, omega, zeta)
    k3x = v + 0.5 * dt * k2v
    k3v = _accel(x + 0.5 * dt * k2x, k3x, force, omega, zeta)
    k4x = v + dt * k3v
    k4v = _accel(x + dt * k3x, k4x, force, omega, zeta)
    x += dt / 6.0 * (k1x + 2.0 * k2x + 2.0 * k3x + k4x)
    v += dt / 6.0 * (k1v + 2.0 * k2v + 2.0 * k3v + k4v)
    return x, v


def _active_fault(faults: Sequence[Fault], t: float) -> Fault | None:
    for fault in faults:
        if fault.contains(t):
            return fault
    return None


def simulate(cfg: SensorConfig, faults: Sequence[Fault] = ()) -> Iterator[Sample]:
    """Yield samples forever, one at a time; the caller decides when to stop."""
    rng = np.random.default_rng(cfg.seed)
    dt = 1.0 / cfg.fs
    omega_n = 2.0 * math.pi * cfg.f_n_hz
    x = v = 0.0
    n = 0
    while True:
        # Time from the integer index, so it never drifts from accumulating dt.
        t = n / cfg.fs
        fault = _active_fault(faults, t)
        omega, zeta = omega_n, cfg.zeta
        if fault is not None:
            omega *= fault.omega_scale
            zeta *= fault.zeta_scale
        force = float(rng.normal(0.0, cfg.noise_std))
        yield Sample(t=t, accel=_accel(x, v, force, omega, zeta), in_fault=bool(fault))
        x, v = _rk4_step(x, v, force, omega, zeta, dt)
        n += 1
