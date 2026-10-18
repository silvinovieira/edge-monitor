"""Sensor configuration, read once from environment variables."""

import math
import os
from dataclasses import dataclass

from sensor.simulator import Fault


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None or value == "" else float(value)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value == "" else int(value)


@dataclass(frozen=True)
class SensorConfig:
    fs: int = 1000
    f_n_hz: float = 50.0
    zeta: float = 0.05
    noise_std: float = 1.0
    seed: int = 0
    fault_start: float = 20.0
    fault_duration: float = 10.0
    fault_omega_scale: float = 1.3
    fault_zeta_scale: float = 0.5

    def __post_init__(self) -> None:
        if self.fs <= 0:
            raise ValueError("fs must be positive")
        if self.f_n_hz <= 0 or self.zeta < 0 or self.noise_std < 0:
            raise ValueError("f_n_hz must be positive; zeta, noise_std non-negative")
        # RK4 on an oscillator is only stable for omega*dt below ~2.8; keep a
        # wide margin so the faulted frequency is also integrated accurately.
        max_omega = 2 * math.pi * self.f_n_hz * max(1, self.fault_omega_scale)
        if max_omega / self.fs > 1.0:
            raise ValueError("fs too low for the (faulted) natural frequency")

    @classmethod
    def from_env(cls) -> "SensorConfig":
        return cls(
            fs=_env_int("SENSOR_FS", cls.fs),
            f_n_hz=_env_float("SENSOR_F_N_HZ", cls.f_n_hz),
            zeta=_env_float("SENSOR_ZETA", cls.zeta),
            noise_std=_env_float("SENSOR_NOISE_STD", cls.noise_std),
            seed=_env_int("SENSOR_SEED", cls.seed),
            fault_start=_env_float("SENSOR_FAULT_START", cls.fault_start),
            fault_duration=_env_float("SENSOR_FAULT_DURATION", cls.fault_duration),
            fault_omega_scale=_env_float(
                "SENSOR_FAULT_OMEGA_SCALE", cls.fault_omega_scale
            ),
            fault_zeta_scale=_env_float(
                "SENSOR_FAULT_ZETA_SCALE", cls.fault_zeta_scale
            ),
        )

    def default_fault(self) -> Fault:
        return Fault(
            start=self.fault_start,
            duration=self.fault_duration,
            omega_scale=self.fault_omega_scale,
            zeta_scale=self.fault_zeta_scale,
        )
