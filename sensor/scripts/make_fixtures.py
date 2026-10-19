"""Write the recordings that processing tests against to docs/contract/fixtures/.

Usage (from sensor/): uv run python scripts/make_fixtures.py
"""

import logging
from itertools import islice
from pathlib import Path

import numpy as np

from sensor.config import SensorConfig
from sensor.simulator import get_fault_ranges, simulate

SEEDS = range(5)
DURATION_S = 40
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "contract" / "fixtures"

log = logging.getLogger(__name__)


def write_fixture(seed: int, path: Path) -> None:
    # Documented defaults only, never the caller's environment, so the
    # committed files can always be regenerated identically.
    cfg = SensorConfig(seed=seed)
    fault = cfg.default_fault()
    sample_count = DURATION_S * cfg.sample_rate_hz
    samples = islice(simulate(cfg, [fault]), sample_count)
    acceleration = np.array([s.acceleration for s in samples], dtype=np.float32)
    [(fault_samples, _)] = get_fault_ranges(cfg, [fault])
    np.savez_compressed(
        path,
        acceleration=acceleration,
        sample_rate_hz=cfg.sample_rate_hz,
        fault_start=fault_samples.start,
        fault_stop=fault_samples.stop,
    )
    log.info("wrote %s", path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        write_fixture(seed, OUTPUT_DIR / f"seed_{seed}.npz")


if __name__ == "__main__":
    main()
