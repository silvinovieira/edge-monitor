import pytest

from processing.config import ProcessingConfig
from processing.detector import Detector, RunningStats
from processing.evaluate import Evaluator, evaluate
from processing.features import Features
from processing.processor import process

CFG = ProcessingConfig()
NORMAL = Features(rms=1.0, mean=0.0, std=1.0, peak_hz=50.0)


def _evaluate_recording(recording: dict):
    acceleration = recording["acceleration"].astype(float)
    chunks = (acceleration[i : i + 50] for i in range(0, len(acceleration), 50))
    return evaluate(
        process(chunks, CFG),
        int(recording["fault_start"]),
        int(recording["fault_stop"]),
        CFG,
    )


def test_running_stats_match_mean_and_std():
    stats = RunningStats()
    for value in [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]:
        stats.add(value)
    assert stats.mean == pytest.approx(5.0)
    assert stats.std == pytest.approx(2.0)


def _make_detector() -> Detector:
    detector = Detector(warmup_windows=3, z_threshold=4.0, consecutive_windows=2)
    for rms in [0.9, 1.0, 1.1]:
        assert not detector.check(Features(rms=rms, mean=0.0, std=1.0, peak_hz=50.0))
    return detector


def test_one_outlier_window_is_not_an_anomaly():
    detector = _make_detector()
    outlier = Features(rms=5.0, mean=0.0, std=1.0, peak_hz=50.0)
    assert not detector.check(outlier)
    assert not detector.check(NORMAL)
    assert not detector.check(outlier)


def test_two_outlier_windows_in_a_row_are_an_anomaly():
    detector = _make_detector()
    outlier = Features(rms=5.0, mean=0.0, std=1.0, peak_hz=50.0)
    assert not detector.check(outlier)
    assert detector.check(outlier)
    assert not detector.check(NORMAL)


def test_detector_finds_the_fault_in_every_recording(recordings):
    evaluations = [_evaluate_recording(recording) for recording in recordings]
    for evaluation in evaluations:
        assert evaluation.latency_s is not None
        assert evaluation.latency_s < 1.5
    mean_precision = sum(e.precision for e in evaluations) / len(evaluations)
    mean_recall = sum(e.recall for e in evaluations) / len(evaluations)
    assert mean_precision >= 0.8
    assert mean_recall >= 0.8


def test_incremental_evaluator_matches_evaluate(recordings):
    recording = recordings[0]
    results = list(process([recording["acceleration"].astype(float)], CFG))
    start, stop = int(recording["fault_start"]), int(recording["fault_stop"])
    evaluator = Evaluator(start, stop, CFG)
    for result in results:
        evaluator.add(result)
    assert evaluator.get_evaluation() == evaluate(results, start, stop, CFG)
