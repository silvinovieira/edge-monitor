import json
import threading
from dataclasses import dataclass

from processing.subscriber import Subscriber, get_first_sample


@dataclass
class FakeMessage:
    """What paho passes to on_message: a topic and a bytes payload."""

    topic: str
    payload: bytes


def _send_chunk(subscriber: Subscriber, seq: int) -> None:
    payload = {
        "sensor_id": "sensor-1",
        "seq": seq,
        "t0_ns": 0,
        "dt_s": 0.001,
        "values": [float(seq)],
    }
    message = FakeMessage("sensors/sensor-1/samples", json.dumps(payload).encode())
    subscriber.on_message(None, None, message)


def _drain(subscriber: Subscriber, count: int) -> list[dict]:
    stop = threading.Event()
    messages = []
    for message in subscriber.iterate_messages(stop):
        messages.append(message)
        if len(messages) == count:
            stop.set()
    return messages


def test_chunks_arrive_in_order():
    subscriber = Subscriber("sensor-1", queue_size=10)
    for seq in range(3):
        _send_chunk(subscriber, seq)
    assert [m["seq"] for m in _drain(subscriber, 3)] == [0, 1, 2]
    assert subscriber.seq_gaps == 0


def test_full_queue_drops_the_oldest_and_counts_it():
    subscriber = Subscriber("sensor-1", queue_size=3)
    for seq in range(5):
        _send_chunk(subscriber, seq)
    assert subscriber.dropped_messages == 2
    assert [m["seq"] for m in _drain(subscriber, 3)] == [2, 3, 4]


def test_seq_gaps_are_counted():
    subscriber = Subscriber("sensor-1", queue_size=10)
    for seq in [0, 1, 5, 6]:
        _send_chunk(subscriber, seq)
    _drain(subscriber, 4)
    assert subscriber.seq_gaps == 1


def test_truth_is_kept_and_never_queued():
    subscriber = Subscriber("sensor-1", queue_size=10)
    truth = {"faults": [{"start_sample": 20_000, "stop_sample": 30_000}]}
    subscriber.on_message(
        None, None, FakeMessage("sensors/sensor-1/truth", json.dumps(truth).encode())
    )
    assert subscriber.faults == [(20_000, 30_000)]
    _send_chunk(subscriber, 0)
    assert [m["seq"] for m in _drain(subscriber, 1)] == [0]


def test_other_sensors_are_ignored():
    subscriber = Subscriber("sensor-1", queue_size=10)
    message = FakeMessage("sensors/sensor-2/samples", json.dumps({"seq": 0}).encode())
    subscriber.on_message(None, None, message)
    _send_chunk(subscriber, 7)
    assert [m["seq"] for m in _drain(subscriber, 1)] == [7]


def test_iteration_ends_when_stopped():
    stop = threading.Event()
    stop.set()
    assert list(Subscriber("sensor-1", queue_size=1).iterate_messages(stop)) == []


def test_first_sample_after_a_restart():
    # Processing restarted while the sensor was at chunk 6000 (5 minutes in).
    message = {"seq": 6000, "values": [0.0] * 50}
    assert get_first_sample(message) == 300_000
