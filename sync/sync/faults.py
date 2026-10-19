"""Simulated bad connectivity, so the retry path runs all the time."""

import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from sync.uploader import Uploader, UploadError


class FlakyUploader:
    """Wraps an uploader and makes some uploads fail before they start.

    Two kinds of failure:
    - random: each upload fails with probability `failure_rate`;
    - outage: the last `outage_s` of every `outage_every_s` period, all
      uploads fail, like a link that drops for a minute every few minutes.
    """

    def __init__(
        self,
        uploader: Uploader,
        failure_rate: float,
        outage_every_s: float,
        outage_s: float,
        rng: np.random.Generator,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._uploader = uploader
        self._failure_rate = failure_rate
        self._outage_every_s = outage_every_s
        self._outage_s = outage_s
        self._rng = rng
        self._clock = clock
        self._started = clock()

    def upload(self, path: Path) -> str:
        if self._is_in_outage():
            raise UploadError("simulated outage")
        if self._rng.random() < self._failure_rate:
            raise UploadError("simulated failure")
        return self._uploader.upload(path)

    def _is_in_outage(self) -> bool:
        if self._outage_s <= 0:
            return False
        elapsed = self._clock() - self._started
        # The outage is at the end of each period, so a fresh start is healthy.
        return elapsed % self._outage_every_s >= self._outage_every_s - self._outage_s
