"""Receives sample chunks over MQTT and hands them to the processing loop.

paho calls `on_message` on its own network thread. The messages go through a
bounded queue, so a slow loop can never make memory grow: when the queue is
full, the oldest message is dropped and counted.
"""

import json
import logging
import queue
import threading
from collections.abc import Iterator

log = logging.getLogger(__name__)

GET_TIMEOUT_S = 0.5


def get_samples_topic(sensor_id: str) -> str:
    return f"sensors/{sensor_id}/samples"


def get_truth_topic(sensor_id: str) -> str:
    return f"sensors/{sensor_id}/truth"


def get_first_sample(message: dict) -> int:
    """Return the sensor's index of the first sample in this message."""
    # Every chunk has the same length, so seq counts in steps of it.
    return message["seq"] * len(message["values"])


def check_samples_message(payload: object) -> dict:
    """Return the payload if it is a well-formed samples message."""
    is_valid = (
        isinstance(payload, dict)
        and isinstance(payload.get("seq"), int)
        and isinstance(payload.get("t0_ns"), int)
        and isinstance(payload.get("dt_s"), int | float)
        and payload["dt_s"] > 0
        and isinstance(payload.get("values"), list)
        and len(payload["values"]) > 0
        and all(isinstance(value, int | float) for value in payload["values"])
    )
    if not is_valid:
        raise ValueError("not a samples message")
    return payload


class Subscriber:
    def __init__(self, sensor_id: str, queue_size: int) -> None:
        self._samples_topic = get_samples_topic(sensor_id)
        self._truth_topic = get_truth_topic(sensor_id)
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=queue_size)
        self.dropped_messages = 0
        self.invalid_messages = 0
        self.seq_gaps = 0
        # Fault windows as (start_sample, stop_sample); set by the truth topic.
        self.faults: list[tuple[int, int]] | None = None

    def on_message(self, client, userdata, message) -> None:
        """paho callback; runs on the MQTT network thread."""
        # An exception escaping from here kills paho's network thread, and with
        # it all input, so a bad message is counted and dropped instead.
        try:
            payload = json.loads(message.payload)
            if message.topic == self._truth_topic:
                self.faults = [
                    (f["start_sample"], f["stop_sample"]) for f in payload["faults"]
                ]
                log.info("ground truth: faults %s", self.faults)
            elif message.topic == self._samples_topic:
                self._put_dropping_oldest(check_samples_message(payload))
        except (ValueError, KeyError, TypeError) as error:
            self.invalid_messages += 1
            log.warning("ignored invalid message on %s: %s", message.topic, error)

    def _put_dropping_oldest(self, payload: dict) -> None:
        # Only this thread puts, so after one get there is always room.
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._queue.get_nowait()
            self.dropped_messages += 1
            log.warning(
                "queue full; dropped the oldest chunk (%d so far)",
                self.dropped_messages,
            )
            self._queue.put_nowait(payload)

    def iterate_messages(self, stop: threading.Event) -> Iterator[dict]:
        """Yield sample messages in arrival order until `stop` is set."""
        expected_seq = None
        while not stop.is_set():
            try:
                message = self._queue.get(timeout=GET_TIMEOUT_S)
            except queue.Empty:
                continue
            if expected_seq is not None and message["seq"] != expected_seq:
                # Processing carries on as if the stream were contiguous, so
                # later timestamps shift by the missing samples.
                self.seq_gaps += 1
                log.warning(
                    "seq gap: expected %d, got %d", expected_seq, message["seq"]
                )
            expected_seq = message["seq"] + 1
            yield message
