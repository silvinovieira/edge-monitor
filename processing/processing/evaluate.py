"""Scores the detector's flags against the known fault window."""

from collections.abc import Iterable
from dataclasses import dataclass

from processing.config import ProcessingConfig
from processing.processor import WindowResult


@dataclass(frozen=True)
class Evaluation:
    true_positives: int
    false_positives: int
    false_negatives: int
    # Seconds from fault start to the first flagged window; None if missed.
    latency_s: float | None

    @property
    def precision(self) -> float:
        flagged = self.true_positives + self.false_positives
        return self.true_positives / flagged if flagged else 0.0

    @property
    def recall(self) -> float:
        faulty = self.true_positives + self.false_negatives
        return self.true_positives / faulty if faulty else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


def evaluate(
    results: Iterable[WindowResult],
    fault_start: int,
    fault_stop: int,
    cfg: ProcessingConfig,
) -> Evaluation:
    """Compare flags with the fault, given as sample indices [start, stop).

    A window counts as faulty when at least half of it lies inside the fault.
    """
    true_positives = false_positives = false_negatives = 0
    latency_s = None
    for result in results:
        is_faulty = _get_fault_overlap(result, fault_start, fault_stop, cfg) >= 0.5
        if result.is_anomaly and is_faulty:
            true_positives += 1
        elif result.is_anomaly:
            false_positives += 1
        elif is_faulty:
            false_negatives += 1
        is_during_fault = fault_start < result.end_sample <= fault_stop
        if result.is_anomaly and is_during_fault and latency_s is None:
            latency_s = (result.end_sample - fault_start) / cfg.sample_rate_hz
    return Evaluation(true_positives, false_positives, false_negatives, latency_s)


def _get_fault_overlap(
    result: WindowResult, fault_start: int, fault_stop: int, cfg: ProcessingConfig
) -> float:
    """Return the fraction of the window that lies inside the fault."""
    overlap = min(result.end_sample, fault_stop) - max(result.start_sample, fault_start)
    return max(overlap, 0) / cfg.window_size
