"""The processing loop: samples in, one result per window out."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from processing.config import ProcessingConfig
from processing.detector import Detector
from processing.features import Features, compute_features
from processing.ring_buffer import RingBuffer


@dataclass(frozen=True)
class WindowResult:
    # The window covers samples [start_sample, end_sample).
    start_sample: int
    end_sample: int
    features: Features
    is_anomaly: bool


class Processor:
    """Produces a result every `hop_size` samples once the window is full.

    Each result uses only samples already received, so there is no look-ahead.
    """

    def __init__(self, cfg: ProcessingConfig) -> None:
        self._cfg = cfg
        self._window = RingBuffer(cfg.window_size)
        self._detector = Detector(
            cfg.warmup_windows, cfg.z_threshold, cfg.consecutive_windows
        )
        self._sample_count = 0

    def add_chunk(self, chunk: Iterable[float]) -> list[WindowResult]:
        """Add samples and return the results of the windows they complete."""
        results = []
        for value in chunk:
            self._window.append(value)
            self._sample_count += 1
            if self._window.is_full and self._sample_count % self._cfg.hop_size == 0:
                results.append(self._evaluate_window())
        return results

    def _evaluate_window(self) -> WindowResult:
        features = compute_features(
            self._window.get_snapshot(), self._cfg.sample_rate_hz
        )
        return WindowResult(
            start_sample=self._sample_count - self._cfg.window_size,
            end_sample=self._sample_count,
            features=features,
            is_anomaly=self._detector.check(features),
        )


def process(
    chunks: Iterable[Iterable[float]], cfg: ProcessingConfig
) -> Iterator[WindowResult]:
    """Run a whole stream through a `Processor`, yielding each result."""
    processor = Processor(cfg)
    for chunk in chunks:
        yield from processor.add_chunk(chunk)
