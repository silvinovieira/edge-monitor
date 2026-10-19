"""Reduces the 1 kHz stream to low-rate summary points for upload."""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SummaryPoint:
    mean: float
    rms: float


class Downsampler:
    """Emits one point (mean and RMS) per `samples_per_point` samples.

    Only one point's worth of samples is held at a time.
    """

    def __init__(self, samples_per_point: int) -> None:
        self._pending = np.zeros(samples_per_point)
        self._count = 0

    def add_chunk(self, chunk: Iterable[float]) -> list[SummaryPoint]:
        points = []
        for value in chunk:
            self._pending[self._count] = value
            self._count += 1
            if self._count == len(self._pending):
                points.append(self._summarise_pending())
                self._count = 0
        return points

    def _summarise_pending(self) -> SummaryPoint:
        return SummaryPoint(
            mean=float(np.mean(self._pending)),
            rms=float(np.sqrt(np.mean(self._pending**2))),
        )
