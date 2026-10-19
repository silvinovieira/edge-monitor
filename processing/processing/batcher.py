"""Groups the processing output into fixed-length batches for the spool.

The batch format is defined in docs/spool-contract.md.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import numpy as np

from processing.config import ProcessingConfig
from processing.downsample import Downsampler, SummaryPoint
from processing.processor import Processor, WindowResult

SPOOL_FORMAT_VERSION = 1
NS_PER_S = 1_000_000_000


@dataclass(frozen=True)
class Batch:
    file_name: str
    # JSON-ready records, one per line of the batch file.
    lines: list[dict]


def make_batches(
    chunks: Iterable[Iterable[float]], cfg: ProcessingConfig, stream_start_ns: int
) -> Iterator[Batch]:
    """Process a stream and yield one batch per `batch_s` of stream time.

    `stream_start_ns` is the wall-clock time of the first sample; every other
    time is derived from the sample index. When the stream ends, the samples
    since the last full batch are yielded as a shorter final batch.
    """
    processor = Processor(cfg)
    downsampler = Downsampler(cfg.samples_per_point)
    batch_start = sample_count = 0
    windows: list[WindowResult] = []
    points: list[SummaryPoint] = []
    for chunk in chunks:
        # Split chunks at batch boundaries, so each sample lands in one batch.
        for piece in _split_at_batch_ends(chunk, sample_count, cfg.batch_samples):
            windows += processor.add_chunk(piece)
            points += downsampler.add_chunk(piece)
            sample_count += len(piece)
            if sample_count - batch_start == cfg.batch_samples:
                yield _build_batch(
                    batch_start, sample_count, windows, points, cfg, stream_start_ns
                )
                batch_start = sample_count
                windows, points = [], []
    if sample_count > batch_start:
        yield _build_batch(
            batch_start, sample_count, windows, points, cfg, stream_start_ns
        )


def _split_at_batch_ends(
    chunk: Iterable[float], sample_count: int, batch_samples: int
) -> Iterator[np.ndarray]:
    remaining = np.asarray(chunk, dtype=float)
    while len(remaining):
        room = batch_samples - sample_count % batch_samples
        piece, remaining = remaining[:room], remaining[room:]
        sample_count += len(piece)
        yield piece


def _build_batch(
    start_sample: int,
    end_sample: int,
    windows: list[WindowResult],
    points: list[SummaryPoint],
    cfg: ProcessingConfig,
    stream_start_ns: int,
) -> Batch:
    def to_ns(sample: int) -> int:
        return stream_start_ns + sample * NS_PER_S // cfg.sample_rate_hz

    start_ns = to_ns(start_sample)
    header = {
        "type": "header",
        "version": SPOOL_FORMAT_VERSION,
        "sensor_id": cfg.sensor_id,
        "start_ns": start_ns,
        "end_ns": to_ns(end_sample),
        "sample_rate_hz": cfg.sample_rate_hz,
        "window_size": cfg.window_size,
        "hop_size": cfg.hop_size,
    }
    window_lines = [
        {
            "type": "window",
            "start_ns": to_ns(window.start_sample),
            "end_ns": to_ns(window.end_sample),
            "rms": window.features.rms,
            "mean": window.features.mean,
            "std": window.features.std,
            "peak_hz": window.features.peak_hz,
            "is_anomaly": window.is_anomaly,
        }
        for window in windows
    ]
    samples_line = {
        "type": "samples_10hz",
        "start_ns": start_ns,
        "interval_ns": NS_PER_S // cfg.summary_rate_hz,
        "mean": [point.mean for point in points],
        "rms": [point.rms for point in points],
    }
    return Batch(
        file_name=f"{start_ns:019d}_{cfg.sensor_id}.jsonl.gz",
        lines=[header, *window_lines, samples_line],
    )
