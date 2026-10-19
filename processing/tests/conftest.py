from pathlib import Path

import numpy as np
import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "docs" / "contract" / "fixtures"


@pytest.fixture(scope="session")
def recordings() -> list[dict]:
    """The sensor recordings: 40 s each, seeds 0-4, fault at 20-30 s."""
    paths = sorted(FIXTURES_DIR.glob("seed_*.npz"))
    assert paths, f"no fixtures in {FIXTURES_DIR}"
    return [dict(np.load(path)) for path in paths]
