import tracemalloc

import numpy as np

from processing.ring_buffer import RingBuffer


def test_snapshot_is_oldest_first_after_wrapping():
    buffer = RingBuffer(4)
    for value in range(10):
        buffer.append(value)
    assert buffer.get_snapshot().tolist() == [6, 7, 8, 9]


def test_snapshot_before_full_holds_only_appended_values():
    buffer = RingBuffer(4)
    buffer.append(1.0)
    buffer.append(2.0)
    assert not buffer.is_full
    assert buffer.get_snapshot().tolist() == [1.0, 2.0]


def test_snapshot_is_a_copy():
    buffer = RingBuffer(2)
    buffer.append(1.0)
    buffer.get_snapshot()[0] = 99.0
    assert buffer.get_snapshot().tolist() == [1.0]


def test_memory_stays_bounded_after_a_million_appends():
    buffer = RingBuffer(1024)
    values = np.random.default_rng(0).normal(size=1_000_000)
    for value in values[:2048]:
        buffer.append(value)

    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    for value in values[2048:]:
        buffer.append(value)
    after, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # A growing buffer would need ~8 MB for a million floats.
    assert after - before < 1024
    assert buffer.capacity == 1024
    assert buffer.get_snapshot().tolist() == values[-1024:].tolist()
