"""Write docs/contract/example_batch.jsonl.gz with the real batcher.

Usage (from processing/): uv run python scripts/make_example_batch.py

The example is the first full 60 s batch of the seed 0 and seed 1 recordings
played back to back, so it contains the fault at 20-30 s. Rerun it whenever the
batch format changes, and commit the result with docs/spool-contract.md.
"""

import logging
from pathlib import Path

import numpy as np

from processing.batcher import make_batches
from processing.config import ProcessingConfig
from processing.spool_writer import encode_batch

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "docs" / "contract"
# 2026-01-01T00:00:00Z, fixed so the example is reproducible.
STREAM_START_NS = 1_767_225_600 * 1_000_000_000

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    recordings = [
        np.load(CONTRACT_DIR / "fixtures" / f"seed_{seed}.npz")["acceleration"]
        for seed in (0, 1)
    ]
    signal = np.concatenate(recordings).astype(float)
    chunks = (signal[i : i + 50] for i in range(0, len(signal), 50))
    # Documented defaults only, never the caller's environment.
    batch = next(make_batches(chunks, ProcessingConfig(), STREAM_START_NS))
    path = CONTRACT_DIR / "example_batch.jsonl.gz"
    path.write_bytes(encode_batch(batch))
    log.info("wrote %s (%s)", path, batch.file_name)


if __name__ == "__main__":
    main()
