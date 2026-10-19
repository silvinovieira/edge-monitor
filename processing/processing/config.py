"""Processing configuration, read once from environment variables."""

import os
from dataclasses import dataclass


def _get_env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None or value == "" else float(value)


def _get_env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value == "" else int(value)


@dataclass(frozen=True)
class ProcessingConfig:
    sample_rate_hz: int = 1000
    # 1024 samples is 1.024 s at 1 kHz: inside the required 1-2 s, and a power
    # of two for the FFT.
    window_size: int = 1024
    # A new window every 250 samples (4 per second).
    hop_size: int = 250
    warmup_s: float = 10.0
    z_threshold: float = 4.0
    consecutive_windows: int = 2

    def __post_init__(self) -> None:
        if min(self.sample_rate_hz, self.window_size, self.hop_size) <= 0:
            raise ValueError(
                "sample_rate_hz, window_size and hop_size must be positive"
            )

    @property
    def warmup_windows(self) -> int:
        return int(self.warmup_s * self.sample_rate_hz / self.hop_size)

    @classmethod
    def from_env(cls) -> "ProcessingConfig":
        return cls(
            sample_rate_hz=_get_env_int(
                "PROCESSING_SAMPLE_RATE_HZ", cls.sample_rate_hz
            ),
            window_size=_get_env_int("PROCESSING_WINDOW_SIZE", cls.window_size),
            hop_size=_get_env_int("PROCESSING_HOP_SIZE", cls.hop_size),
            warmup_s=_get_env_float("PROCESSING_WARMUP_S", cls.warmup_s),
            z_threshold=_get_env_float("PROCESSING_Z_THRESHOLD", cls.z_threshold),
            consecutive_windows=_get_env_int(
                "PROCESSING_CONSECUTIVE_WINDOWS", cls.consecutive_windows
            ),
        )
