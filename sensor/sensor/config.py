"""Sensor configuration, read once from environment variables."""

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None or value == "" else float(value)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value == "" else int(value)


@dataclass(frozen=True)
class Fault:
    """Scales frequency and damping in the half-open window [start, start + duration).

    Times are in seconds of stream time.
    """

    start: float
    duration: float
    freq_scale: float = 1.0
    damping_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.start < 0 or self.duration <= 0:
            raise ValueError("fault needs start >= 0 and duration > 0")
        if self.freq_scale <= 0 or self.damping_scale < 0:
            raise ValueError("fault needs freq_scale > 0 and damping_scale >= 0")

    @property
    def end(self) -> float:
        return self.start + self.duration

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end


@dataclass(frozen=True)
class SensorConfig:
    sample_rate_hz: int = 1000
    natural_freq_hz: float = 50.0
    damping_ratio: float = 0.05
    # Std of the forcing per sample at sample_rate_hz; it is not rescaled with
    # the step length, so changing the sample rate changes the response level.
    noise_std: float = 1.0
    seed: int = 0
    fault_start: float = 20.0
    fault_duration: float = 10.0
    fault_freq_scale: float = 1.3
    fault_damping_scale: float = 0.5

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0 or self.natural_freq_hz <= 0:
            raise ValueError("sample_rate_hz and natural_freq_hz must be positive")
        if self.damping_ratio < 0 or self.noise_std < 0:
            raise ValueError("damping_ratio and noise_std must be non-negative")

    @classmethod
    def from_env(cls) -> "SensorConfig":
        return cls(
            sample_rate_hz=_env_int("SENSOR_SAMPLE_RATE_HZ", cls.sample_rate_hz),
            natural_freq_hz=_env_float("SENSOR_NATURAL_FREQ_HZ", cls.natural_freq_hz),
            damping_ratio=_env_float("SENSOR_DAMPING_RATIO", cls.damping_ratio),
            noise_std=_env_float("SENSOR_NOISE_STD", cls.noise_std),
            seed=_env_int("SENSOR_SEED", cls.seed),
            fault_start=_env_float("SENSOR_FAULT_START", cls.fault_start),
            fault_duration=_env_float("SENSOR_FAULT_DURATION", cls.fault_duration),
            fault_freq_scale=_env_float(
                "SENSOR_FAULT_FREQ_SCALE", cls.fault_freq_scale
            ),
            fault_damping_scale=_env_float(
                "SENSOR_FAULT_DAMPING_SCALE", cls.fault_damping_scale
            ),
        )

    def default_fault(self) -> Fault:
        return Fault(
            start=self.fault_start,
            duration=self.fault_duration,
            freq_scale=self.fault_freq_scale,
            damping_scale=self.fault_damping_scale,
        )
