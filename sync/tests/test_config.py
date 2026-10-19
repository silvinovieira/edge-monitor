from pathlib import Path

import pytest

from sync.config import SyncConfig


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SYNC_SPOOL_DIR", "/data/spool")
    monkeypatch.setenv("SYNC_ENDPOINT_URL", "http://localhost:4566")
    monkeypatch.setenv("SYNC_CREATE_BUCKET", "true")
    monkeypatch.setenv("SYNC_FAILURE_RATE", "0")
    cfg = SyncConfig.from_env()
    assert cfg.spool_dir == Path("/data/spool")
    assert cfg.endpoint_url == "http://localhost:4566"
    assert cfg.create_bucket and cfg.failure_rate == 0.0
    assert cfg.bucket == "edge-monitor" and cfg.backoff_cap_s == 60.0


def test_endpoint_defaults_to_real_aws():
    assert SyncConfig().endpoint_url is None


@pytest.mark.parametrize(
    "kwargs", [{"failure_rate": 1.5}, {"outage_s": 400.0, "outage_every_s": 300.0}]
)
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        SyncConfig(**kwargs)
