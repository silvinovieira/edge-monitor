import numpy as np

from processing.batcher import make_batches
from processing.config import ProcessingConfig

CFG = ProcessingConfig()
START_NS = 1_767_225_600 * 1_000_000_000
SIGNAL = np.random.default_rng(0).normal(size=150_000)  # 150 s at 1 kHz


def _make_batches(chunk_size: int):
    chunks = (SIGNAL[i : i + chunk_size] for i in range(0, len(SIGNAL), chunk_size))
    return list(make_batches(chunks, CFG, START_NS))


def test_a_batch_per_minute_and_a_shorter_last_batch():
    headers = [batch.lines[0] for batch in _make_batches(50)]
    durations_s = [(h["end_ns"] - h["start_ns"]) / 1e9 for h in headers]
    assert durations_s == [60.0, 60.0, 30.0]
    assert headers[1]["start_ns"] == START_NS + 60 * 1_000_000_000


def test_batch_holds_its_minute_of_windows_and_points():
    batch = _make_batches(50)[1]
    header, *windows, samples = batch.lines
    assert len(windows) == 240  # 4 per second
    assert all(header["start_ns"] < w["end_ns"] <= header["end_ns"] for w in windows)
    assert len(samples["mean"]) == len(samples["rms"]) == 600  # 10 per second


def test_file_name_is_start_time_then_sensor_id():
    assert _make_batches(50)[0].file_name == f"{START_NS}_sensor-1.jsonl.gz"


def test_chunk_size_does_not_change_batches():
    # 777 doesn't divide 60 000, so chunks straddle batch boundaries.
    assert _make_batches(777) == _make_batches(50)
