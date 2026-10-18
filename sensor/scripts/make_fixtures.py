"""Write the shared test fixtures to docs/contract/fixtures/.

Usage (from sensor/): uv run python scripts/make_fixtures.py
"""

import logging
from dataclasses import replace
from itertools import islice
from pathlib import Path

import numpy as np

from sensor.config import SensorConfig
from sensor.simulator import simulate

SEEDS = range(5)
DURATION_S = 40
OUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "contract" / "fixtures"

log = logging.getLogger("make_fixtures")


def make_fixture(cfg: SensorConfig, path: Path) -> None:
    faults = [cfg.default_fault()]
    n = DURATION_S * cfg.fs
    accel = np.fromiter(
        (s.accel for s in islice(simulate(cfg, faults), n)), dtype=np.float32, count=n
    )
    windows = np.array([[f.start, f.end] for f in faults], dtype=np.float64)
    np.savez_compressed(
        path, accel=accel, fault_windows=windows, fs=cfg.fs, seed=cfg.seed
    )
    log.info("wrote %s (%d samples)", path, n)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Fixtures use the documented defaults, never the caller's environment.
    base = SensorConfig()
    for seed in SEEDS:
        make_fixture(replace(base, seed=seed), OUT_DIR / f"seed_{seed}.npz")


if __name__ == "__main__":
    main()
