import numpy as np

from processing.config import ProcessingConfig
from processing.processor import process

CFG = ProcessingConfig()


def _run(signal: np.ndarray):
    return list(process([signal], CFG))


def test_a_result_every_hop_once_the_window_is_full():
    results = _run(np.random.default_rng(0).normal(size=3000))
    assert [r.end_sample for r in results] == [
        1250,
        1500,
        1750,
        2000,
        2250,
        2500,
        2750,
        3000,
    ]


def test_results_do_not_depend_on_future_samples():
    signal = np.random.default_rng(0).normal(size=20_000)
    changed_future = signal.copy()
    changed_future[12_000:] *= 10
    past = [r for r in _run(signal) if r.end_sample <= 12_000]
    past_with_changed_future = [
        r for r in _run(changed_future) if r.end_sample <= 12_000
    ]
    assert past == past_with_changed_future


def test_chunk_boundaries_do_not_change_results():
    signal = np.random.default_rng(0).normal(size=5000)
    in_one_chunk = list(process([signal], CFG))
    in_small_chunks = list(process(np.array_split(signal, 97), CFG))
    assert in_one_chunk == in_small_chunks
