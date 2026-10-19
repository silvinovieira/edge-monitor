"""Publishes the simulated samples over MQTT in real time.

Topics (QoS 1):
- sensors/<id>/samples: one message per 50 samples,
  {"sensor_id", "seq", "t0_ns", "dt_s", "values"}
- sensors/<id>/truth: the fault windows as sample indices, published once and
  retained, {"faults": [{"start_sample", "stop_sample"}]}. Only the evaluator
  reads it; the detector never does.
"""

import json
import logging
from collections.abc import Callable, Iterable, Iterator
from itertools import batched

from sensor.simulator import Sample

log = logging.getLogger(__name__)

CHUNK_SIZE = 50
NS_PER_S = 1_000_000_000


def get_samples_topic(sensor_id: str) -> str:
    return f"sensors/{sensor_id}/samples"


def get_truth_topic(sensor_id: str) -> str:
    return f"sensors/{sensor_id}/truth"


def make_truth_message(fault_ranges: Iterable[range]) -> dict:
    faults = [{"start_sample": r.start, "stop_sample": r.stop} for r in fault_ranges]
    return {"faults": faults}


def make_sample_messages(
    samples: Iterable[Sample], sensor_id: str, sample_rate_hz: int, start_ns: int
) -> Iterator[dict]:
    """Group samples into chunks; `start_ns` is the wall-clock time of sample 0."""
    for seq, chunk in enumerate(batched(samples, CHUNK_SIZE)):
        first_sample = seq * CHUNK_SIZE
        yield {
            "sensor_id": sensor_id,
            "seq": seq,
            "t0_ns": start_ns + first_sample * NS_PER_S // sample_rate_hz,
            "dt_s": 1 / sample_rate_hz,
            "values": [sample.acceleration for sample in chunk],
        }


def publish_in_real_time(
    messages: Iterable[dict],
    publish: Callable[[dict], None],
    get_time_ns: Callable[[], int],
    wait: Callable[[float], bool],
) -> None:
    """Publish each chunk when its last sample would exist in real life.

    Deadlines are absolute (from each chunk's t0_ns), so time spent simulating
    or publishing never accumulates into drift. `wait` returns True when the
    publisher should stop, like `threading.Event.wait`.
    """
    for message in messages:
        chunk_ns = len(message["values"]) * round(message["dt_s"] * NS_PER_S)
        delay_s = (message["t0_ns"] + chunk_ns - get_time_ns()) / NS_PER_S
        if wait(max(delay_s, 0.0)):
            return
        publish(message)


def encode(message: dict) -> str:
    return json.dumps(message, separators=(",", ":"))
