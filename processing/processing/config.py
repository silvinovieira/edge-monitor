"""Processing configuration, read once from environment variables."""

import os
import re
from dataclasses import dataclass
from pathlib import Path


def _get_env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None or value == "" else float(value)


def _get_env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value == "" else int(value)


def _get_env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None or value == "" else value.lower() in {"1", "true"}


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
    # Used in spool file names, which use "_" as a separator.
    sensor_id: str = "sensor-1"
    spool_dir: Path = Path("spool")
    batch_s: int = 60
    # Rate of the downsampled samples stored in each batch.
    summary_rate_hz: int = 10
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    # Messages waiting between the MQTT thread and the loop; 1000 chunks of 50
    # samples is 50 s of data. When full, the oldest message is dropped.
    queue_size: int = 1000
    # Subscribe to the ground truth and log precision/recall at shutdown.
    evaluate: bool = False

    def __post_init__(self) -> None:
        if min(self.sample_rate_hz, self.window_size, self.hop_size) <= 0:
            raise ValueError(
                "sample_rate_hz, window_size and hop_size must be positive"
            )
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.sensor_id):
            raise ValueError("sensor_id may only contain letters, digits and '-'")
        # Batches must hold whole summary points, so points never span two files.
        if self.batch_samples % self.samples_per_point != 0:
            raise ValueError("batch length must be a whole number of summary points")

    @property
    def warmup_windows(self) -> int:
        return int(self.warmup_s * self.sample_rate_hz / self.hop_size)

    @property
    def batch_samples(self) -> int:
        return self.batch_s * self.sample_rate_hz

    @property
    def samples_per_point(self) -> int:
        return self.sample_rate_hz // self.summary_rate_hz

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
            sensor_id=os.environ.get("PROCESSING_SENSOR_ID") or cls.sensor_id,
            spool_dir=Path(os.environ.get("PROCESSING_SPOOL_DIR") or cls.spool_dir),
            batch_s=_get_env_int("PROCESSING_BATCH_S", cls.batch_s),
            summary_rate_hz=_get_env_int(
                "PROCESSING_SUMMARY_RATE_HZ", cls.summary_rate_hz
            ),
            mqtt_host=os.environ.get("PROCESSING_MQTT_HOST") or cls.mqtt_host,
            mqtt_port=_get_env_int("PROCESSING_MQTT_PORT", cls.mqtt_port),
            queue_size=_get_env_int("PROCESSING_QUEUE_SIZE", cls.queue_size),
            evaluate=_get_env_bool("PROCESSING_EVALUATE", cls.evaluate),
        )
