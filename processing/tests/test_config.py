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


def test_spool_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PROCESSING_SENSOR_ID", "pump-7")
    monkeypatch.setenv("PROCESSING_SPOOL_DIR", str(tmp_path))
    cfg = ProcessingConfig.from_env()
    assert cfg.sensor_id == "pump-7" and cfg.spool_dir == tmp_path
    assert cfg.batch_samples == 60_000 and cfg.samples_per_point == 100


@pytest.mark.parametrize(
    "kwargs",
    [{"sensor_id": "pump_7"}, {"sensor_id": ""}, {"batch_s": 1, "summary_rate_hz": 3}],
)
def test_invalid_spool_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ProcessingConfig(**kwargs)


def test_mqtt_settings_from_env(monkeypatch):
    monkeypatch.setenv("PROCESSING_MQTT_HOST", "mosquitto")
    monkeypatch.setenv("PROCESSING_EVALUATE", "true")
    cfg = ProcessingConfig.from_env()
    assert cfg.mqtt_host == "mosquitto" and cfg.mqtt_port == 1883
    assert cfg.evaluate and cfg.queue_size == 1000
