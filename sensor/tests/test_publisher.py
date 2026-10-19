import json
from itertools import islice

from sensor.config import SensorConfig
from sensor.publisher import (
    CHUNK_SIZE,
    encode,
    make_sample_messages,
    make_truth_message,
    publish_in_real_time,
)
from sensor.simulator import get_fault_ranges, simulate

CFG = SensorConfig()
START_NS = 1_767_225_600_000_000_000


def _make_messages(count: int) -> list[dict]:
    samples = simulate(CFG, [CFG.default_fault()])
    messages = make_sample_messages(samples, "sensor-1", CFG.sample_rate_hz, START_NS)
    return list(islice(messages, count))


def test_messages_hold_consecutive_chunks_of_50():
    messages = _make_messages(3)
    assert [m["seq"] for m in messages] == [0, 1, 2]
    assert all(len(m["values"]) == CHUNK_SIZE for m in messages)
    assert messages[0]["values"] == [
        s.acceleration for s in islice(simulate(CFG, [CFG.default_fault()]), 50)
    ]


def test_message_format():
    message = json.loads(encode(_make_messages(2)[1]))
    assert message.keys() == {"sensor_id", "seq", "t0_ns", "dt_s", "values"}
    assert message["sensor_id"] == "sensor-1"
    assert message["t0_ns"] == START_NS + 50_000_000  # 50 samples at 1 kHz
    assert message["dt_s"] == 0.001


def test_truth_message_holds_the_fault_as_sample_indices():
    ranges = [samples for samples, _ in get_fault_ranges(CFG, [CFG.default_fault()])]
    assert make_truth_message(ranges) == {
        "faults": [{"start_sample": 20_000, "stop_sample": 30_000}]
    }


class FakeTime:
    """A clock that only moves when the publisher waits."""

    def __init__(self, now_ns: int) -> None:
        self.now_ns = now_ns
        self.waits: list[float] = []

    def get_time_ns(self) -> int:
        return self.now_ns

    def wait(self, seconds: float) -> bool:
        self.waits.append(round(seconds, 6))
        self.now_ns += round(seconds * 1e9) + 3_000_000  # 3 ms of overrun
        return False


def test_each_chunk_waits_for_its_absolute_deadline():
    clock = FakeTime(START_NS)
    published = []
    publish_in_real_time(
        _make_messages(4), published.append, clock.get_time_ns, clock.wait
    )
    assert len(published) == 4
    # The 3 ms overrun of each wait is taken off the next one: no drift.
    assert clock.waits == [0.05, 0.047, 0.047, 0.047]


def test_late_chunks_are_published_at_once():
    clock = FakeTime(START_NS + 10 * 1_000_000_000)  # 10 s behind
    publish_in_real_time(
        _make_messages(3), lambda m: None, clock.get_time_ns, clock.wait
    )
    assert clock.waits == [0.0, 0.0, 0.0]


def test_stops_when_wait_says_so():
    published = []
    publish_in_real_time(
        _make_messages(5), published.append, lambda: START_NS, lambda s: True
    )
    assert published == []
