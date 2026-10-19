from pathlib import Path

import numpy as np
import pytest

from sync.faults import FlakyUploader
from sync.uploader import UploadError


class AlwaysWorks:
    def upload(self, path: Path) -> str:
        return path.name


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _count_failures(uploader: FlakyUploader, attempts: int) -> int:
    failures = 0
    for _ in range(attempts):
        try:
            uploader.upload(Path("batch"))
        except UploadError:
            failures += 1
    return failures


def _make_flaky(failure_rate=0.0, outage_s=0.0, clock=None, seed=0) -> FlakyUploader:
    return FlakyUploader(
        AlwaysWorks(),
        failure_rate=failure_rate,
        outage_every_s=300.0,
        outage_s=outage_s,
        rng=np.random.default_rng(seed),
        clock=clock or FakeClock(),
    )


def test_random_failures_follow_the_rate():
    assert _count_failures(_make_flaky(failure_rate=0.1), 10_000) == pytest.approx(
        1000, rel=0.1
    )


def test_random_failures_are_reproducible_from_the_seed():
    first = _count_failures(_make_flaky(failure_rate=0.3, seed=5), 100)
    second = _count_failures(_make_flaky(failure_rate=0.3, seed=5), 100)
    assert first == second


def test_outage_is_at_the_end_of_each_period():
    clock = FakeClock()
    uploader = _make_flaky(outage_s=60.0, clock=clock)
    for now, fails in [
        (0, False),
        (239, False),
        (240, True),
        (299, True),
        (300, False),
    ]:
        clock.now = now
        assert _count_failures(uploader, 1) == fails, now


def test_no_faults_when_turned_off():
    assert _count_failures(_make_flaky(), 1000) == 0
