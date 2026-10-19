"""Measure throughput and memory of the processing loop.

Usage (from processing/): uv run python scripts/benchmark.py

Feeds 10 minutes of stream time (the five 40 s fixtures, looped) through the
whole loop as fast as possible, in chunks of 50 samples like the MQTT feed:
processing, batching and gzip encoding. Disk writes are left out, because their
cost depends on the storage, not on this code.
"""

import logging
import time
import tracemalloc
from itertools import cycle, islice
from pathlib import Path

import numpy as np

from processing.batcher import make_batches
from processing.config import ProcessingConfig
from processing.spool_writer import encode_batch

STREAM_S = 600
CHUNK_SIZE = 50
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "docs" / "contract" / "fixtures"

log = logging.getLogger(__name__)


def load_recordings() -> list[np.ndarray]:
    paths = sorted(FIXTURES_DIR.glob("seed_*.npz"))
    return [np.load(path)["acceleration"].astype(float) for path in paths]


def split_into_chunks(recordings: list[np.ndarray]) -> list[np.ndarray]:
    signal = np.concatenate(recordings)
    return [signal[i : i + CHUNK_SIZE] for i in range(0, len(signal), CHUNK_SIZE)]


def get_rss_mb() -> float:
    """Current resident memory of this process (Linux only)."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    raise RuntimeError("VmRSS not found")


def run(chunks: list[np.ndarray], cfg: ProcessingConfig) -> None:
    stream = islice(cycle(chunks), STREAM_S * cfg.sample_rate_hz // CHUNK_SIZE)
    for batch in make_batches(stream, cfg, stream_start_ns=0):
        encode_batch(batch)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = ProcessingConfig()
    # The input is loaded before measuring, so the figures cover only the loop.
    chunks = split_into_chunks(load_recordings())
    sample_count = STREAM_S * cfg.sample_rate_hz

    # Throughput first, without tracemalloc, which slows Python down.
    rss_start_mb = get_rss_mb()
    started = time.perf_counter()
    run(chunks, cfg)
    elapsed_s = time.perf_counter() - started
    rss_end_mb = get_rss_mb()

    tracemalloc.start()
    run(chunks, cfg)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rate = sample_count / elapsed_s
    real_time_factor = rate / cfg.sample_rate_hz
    log.info("stream time:      %d s (%d samples)", STREAM_S, sample_count)
    log.info("wall time:        %.2f s", elapsed_s)
    log.info(
        "throughput:       %.0f samples/s (%.0fx real time)", rate, real_time_factor
    )
    log.info("tracemalloc peak: %.1f KiB", peak_bytes / 1024)
    log.info("RSS start / end:  %.1f / %.1f MiB", rss_start_mb, rss_end_mb)


if __name__ == "__main__":
    main()
