import numpy as np
import pytest

from processing.downsample import Downsampler, SummaryPoint


def test_one_point_per_block_with_mean_and_rms():
    points = Downsampler(4).add_chunk([1.0, -1.0, 1.0, -1.0, 2.0, 2.0, 2.0, 2.0])
    assert points == [SummaryPoint(mean=0.0, rms=1.0), SummaryPoint(mean=2.0, rms=2.0)]


def test_blocks_can_span_chunks():
    downsampler = Downsampler(100)
    signal = np.random.default_rng(0).normal(size=1000)
    points = []
    for chunk in np.array_split(signal, 33):
        points += downsampler.add_chunk(chunk)
    assert len(points) == 10
    assert points[3].mean == pytest.approx(signal[300:400].mean())
    assert points[3].rms == pytest.approx(np.sqrt(np.mean(signal[300:400] ** 2)))


def test_an_unfinished_block_gives_no_point():
    assert Downsampler(100).add_chunk(np.ones(99)) == []
