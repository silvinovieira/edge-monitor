"""The committed example batch must match docs/spool-contract.md and the code."""

import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from processing.batcher import make_batches
from processing.config import ProcessingConfig
from processing.spool_writer import encode_batch

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "docs" / "contract"
EXAMPLE = CONTRACT_DIR / "example_batch.jsonl.gz"
HEADER_KEYS = {
    "type",
    "version",
    "sensor_id",
    "start_ns",
    "end_ns",
    "sample_rate_hz",
    "window_size",
    "hop_size",
}
WINDOW_KEYS = {
    "type",
    "start_ns",
    "end_ns",
    "rms",
    "mean",
    "std",
    "peak_hz",
    "is_anomaly",
}
SAMPLES_KEYS = {"type", "start_ns", "interval_ns", "mean", "rms"}


@pytest.fixture(scope="module")
def lines() -> list[dict]:
    return [
        json.loads(line) for line in gzip.decompress(EXAMPLE.read_bytes()).splitlines()
    ]


def test_first_line_is_the_header(lines):
    header = lines[0]
    assert header.keys() == HEADER_KEYS
    assert header["type"] == "header" and header["version"] == 1


def test_window_lines_lie_inside_the_batch(lines):
    header, *windows, _ = lines
    assert windows
    for window in windows:
        assert window.keys() == WINDOW_KEYS and window["type"] == "window"
        assert header["start_ns"] < window["end_ns"] <= header["end_ns"]


def test_last_line_holds_the_10hz_samples(lines):
    header, samples = lines[0], lines[-1]
    assert samples.keys() == SAMPLES_KEYS and samples["type"] == "samples_10hz"
    duration_ns = header["end_ns"] - header["start_ns"]
    assert (
        len(samples["mean"])
        == len(samples["rms"])
        == duration_ns // samples["interval_ns"]
    )


def test_example_is_what_the_current_code_writes(lines):
    # Fails if the format changes without regenerating the example
    # (scripts/make_example_batch.py) and updating the contract.
    recordings = [np.load(CONTRACT_DIR / "fixtures" / f"seed_{s}.npz") for s in (0, 1)]
    signal = np.concatenate([r["acceleration"] for r in recordings]).astype(float)
    chunks = (signal[i : i + 50] for i in range(0, len(signal), 50))
    start_ns = lines[0]["start_ns"]
    batch = next(make_batches(chunks, ProcessingConfig(), start_ns))
    assert encode_batch(batch) == EXAMPLE.read_bytes()
