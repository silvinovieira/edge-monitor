import pytest

from processing.config import ProcessingConfig


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("PROCESSING_HOP_SIZE", "100")
    monkeypatch.setenv("PROCESSING_Z_THRESHOLD", "3.5")
    cfg = ProcessingConfig.from_env()
    assert cfg.hop_size == 100 and cfg.z_threshold == 3.5 and cfg.window_size == 1024


def test_warmup_is_counted_in_windows():
    assert ProcessingConfig().warmup_windows == 40


def test_invalid_config_is_rejected():
    with pytest.raises(ValueError):
        ProcessingConfig(hop_size=0)
