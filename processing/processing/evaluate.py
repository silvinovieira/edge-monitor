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


class Evaluator:
    """Scores window results one at a time, keeping only counts.

    The fault is given as sample indices [fault_start, fault_stop). A window
    counts as faulty when at least half of it lies inside the fault.
    """

    def __init__(
        self, fault_start: int, fault_stop: int, cfg: ProcessingConfig
    ) -> None:
        self._fault_start = fault_start
        self._fault_stop = fault_stop
        self._cfg = cfg
        self._true_positives = self._false_positives = self._false_negatives = 0
        self._latency_s: float | None = None

    def add(self, result: WindowResult) -> None:
        overlap = _get_fault_overlap(
            result, self._fault_start, self._fault_stop, self._cfg
        )
        is_faulty = overlap >= 0.5
        if result.is_anomaly and is_faulty:
            self._true_positives += 1
        elif result.is_anomaly:
            self._false_positives += 1
        elif is_faulty:
            self._false_negatives += 1
        is_during_fault = self._fault_start < result.end_sample <= self._fault_stop
        if result.is_anomaly and is_during_fault and self._latency_s is None:
            delay_samples = result.end_sample - self._fault_start
            self._latency_s = delay_samples / self._cfg.sample_rate_hz

    def get_evaluation(self) -> Evaluation:
        return Evaluation(
            self._true_positives,
            self._false_positives,
            self._false_negatives,
            self._latency_s,
        )


def evaluate(
    results: Iterable[WindowResult],
    fault_start: int,
    fault_stop: int,
    cfg: ProcessingConfig,
) -> Evaluation:
    """Score a whole run at once; see `Evaluator`."""
    evaluator = Evaluator(fault_start, fault_stop, cfg)
    for result in results:
        evaluator.add(result)
    return evaluator.get_evaluation()


def _get_fault_overlap(
    result: WindowResult, fault_start: int, fault_stop: int, cfg: ProcessingConfig
) -> float:
    """Return the fraction of the window that lies inside the fault."""
    overlap = min(result.end_sample, fault_stop) - max(result.start_sample, fault_start)
    return max(overlap, 0) / cfg.window_size
