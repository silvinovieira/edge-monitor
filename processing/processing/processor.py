"""The processing loop: samples in, one result per window out."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from processing.config import ProcessingConfig
from processing.detector import Detector
from processing.features import Features, compute_features
from processing.ring_buffer import RingBuffer


@dataclass(frozen=True)
class WindowResult:
    # Index one past the newest sample in the window: the window covers
    # samples [end_sample - window_size, end_sample).
    end_sample: int
    features: Features
    is_anomaly: bool


def process(
    chunks: Iterable[Iterable[float]], cfg: ProcessingConfig
) -> Iterator[WindowResult]:
    """Yield a result every `hop_size` samples once the window is full.

    Each result uses only samples already received, so there is no look-ahead.
    """
    window = RingBuffer(cfg.window_size)
    detector = Detector(cfg.warmup_windows, cfg.z_threshold, cfg.consecutive_windows)
    sample_count = 0
    for chunk in chunks:
        for value in chunk:
            window.append(value)
            sample_count += 1
            if window.is_full and sample_count % cfg.hop_size == 0:
                features = compute_features(window.get_snapshot(), cfg.sample_rate_hz)
                yield WindowResult(sample_count, features, detector.check(features))
