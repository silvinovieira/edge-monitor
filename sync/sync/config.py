"""Sync configuration, read once from environment variables."""

import os
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
class SyncConfig:
    spool_dir: Path = Path("spool")
    bucket: str = "edge-monitor"
    # None means real AWS; set it to http://localhost:4566 for LocalStack.
    endpoint_url: str | None = None
    region: str = "us-east-1"
    # Only for LocalStack: on real AWS the bucket is provisioned beforehand.
    create_bucket: bool = False
    poll_s: float = 1.0
    backoff_base_s: float = 1.0
    backoff_cap_s: float = 60.0
    # Simulated bad connectivity, on by default; set both to 0 to turn it off.
    failure_rate: float = 0.1
    outage_every_s: float = 300.0
    outage_s: float = 60.0
    seed: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.failure_rate <= 1:
            raise ValueError("failure_rate must be between 0 and 1")
        if self.outage_s > self.outage_every_s:
            raise ValueError("outage_s can't be longer than outage_every_s")

    @classmethod
    def from_env(cls) -> "SyncConfig":
        return cls(
            spool_dir=Path(os.environ.get("SYNC_SPOOL_DIR") or cls.spool_dir),
            bucket=os.environ.get("SYNC_BUCKET") or cls.bucket,
            endpoint_url=os.environ.get("SYNC_ENDPOINT_URL") or cls.endpoint_url,
            region=os.environ.get("SYNC_REGION") or cls.region,
            create_bucket=_get_env_bool("SYNC_CREATE_BUCKET", cls.create_bucket),
            poll_s=_get_env_float("SYNC_POLL_S", cls.poll_s),
            backoff_base_s=_get_env_float("SYNC_BACKOFF_BASE_S", cls.backoff_base_s),
            backoff_cap_s=_get_env_float("SYNC_BACKOFF_CAP_S", cls.backoff_cap_s),
            failure_rate=_get_env_float("SYNC_FAILURE_RATE", cls.failure_rate),
            outage_every_s=_get_env_float("SYNC_OUTAGE_EVERY_S", cls.outage_every_s),
            outage_s=_get_env_float("SYNC_OUTAGE_S", cls.outage_s),
            seed=_get_env_int("SYNC_SEED", cls.seed),
        )
