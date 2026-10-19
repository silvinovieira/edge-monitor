"""Run processing: python -m processing (MQTT in, spool out)."""

import logging
import signal
import threading
from itertools import chain

import paho.mqtt.client as mqtt

from processing.batcher import make_batches
from processing.config import ProcessingConfig
from processing.evaluate import Evaluator
from processing.spool_writer import SpoolWriter
from processing.subscriber import (
    Subscriber,
    get_first_sample,
    get_samples_topic,
    get_truth_topic,
)

log = logging.getLogger("processing")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = ProcessingConfig.from_env()
    stop = threading.Event()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signal_number, lambda *_: stop.set())

    subscriber = Subscriber(cfg.sensor_id, cfg.queue_size)
    client = _connect(cfg, subscriber)
    writer = SpoolWriter(cfg.spool_dir)
    messages = subscriber.iterate_messages(stop)
    first = next(messages, None)
    if first is None:
        log.info("stopped before any data arrived")
        return
    _check_sample_rate(first, cfg)
    # The loop counts samples from the first message it receives, which is the
    # sensor's sample `first_sample` after a restart; times and fault indices
    # are shifted to match, so batches never reuse an earlier run's names.
    first_sample = get_first_sample(first)
    stream_start_ns = first["t0_ns"]
    chunks = (message["values"] for message in chain([first], messages))

    evaluator = None
    # make_batches yields a shorter final batch once `stop` ends the stream.
    for batch in make_batches(chunks, cfg, stream_start_ns):
        path = writer.write(batch)
        anomalies = sum(window.is_anomaly for window in batch.windows)
        log.info(
            "wrote %s (%d windows, %d anomalous)",
            path.name,
            len(batch.windows),
            anomalies,
        )
        if cfg.evaluate and evaluator is None:
            evaluator = _make_evaluator(subscriber, first_sample, cfg)
        if evaluator:
            for window in batch.windows:
                evaluator.add(window)

    client.loop_stop()
    client.disconnect()
    log.info(
        "dropped chunks: %d, seq gaps: %d",
        subscriber.dropped_messages,
        subscriber.seq_gaps,
    )
    if evaluator:
        _log_evaluation(evaluator)
    log.info("stopped")


def _connect(cfg: ProcessingConfig, subscriber: Subscriber) -> mqtt.Client:
    # A fixed client id and a persistent session: while processing is down,
    # the broker keeps queueing its QoS 1 messages instead of dropping them.
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"processing-{cfg.sensor_id}",
        clean_session=False,
    )
    topics = [(get_samples_topic(cfg.sensor_id), 1)]
    if cfg.evaluate:
        topics.append((get_truth_topic(cfg.sensor_id), 1))

    def on_connect(client, userdata, flags, reason_code, properties) -> None:
        log.info("connected to %s:%d (%s)", cfg.mqtt_host, cfg.mqtt_port, reason_code)
        client.subscribe(topics)

    client.on_connect = on_connect
    client.on_message = subscriber.on_message
    # Connects and reconnects in the background, so the broker may start later.
    client.connect_async(cfg.mqtt_host, cfg.mqtt_port)
    client.loop_start()
    return client


def _check_sample_rate(message: dict, cfg: ProcessingConfig) -> None:
    received_hz = round(1 / message["dt_s"])
    if received_hz != cfg.sample_rate_hz:
        raise ValueError(
            f"stream is {received_hz} Hz, configured for {cfg.sample_rate_hz} Hz"
        )


def _make_evaluator(
    subscriber: Subscriber, first_sample: int, cfg: ProcessingConfig
) -> Evaluator | None:
    if not subscriber.faults:
        log.warning("no ground truth received yet; evaluation waits for it")
        return None
    if len(subscriber.faults) > 1:
        log.warning("only the first of %d faults is evaluated", len(subscriber.faults))
    fault_start, fault_stop = subscriber.faults[0]
    return Evaluator(fault_start - first_sample, fault_stop - first_sample, cfg)


def _log_evaluation(evaluator: Evaluator) -> None:
    result = evaluator.get_evaluation()
    latency = (
        "not detected" if result.latency_s is None else f"{result.latency_s:.2f} s"
    )
    log.info(
        "evaluation: precision %.2f, recall %.2f, F1 %.2f, latency %s (TP %d, FP %d, FN %d)",
        result.precision,
        result.recall,
        result.f1,
        latency,
        result.true_positives,
        result.false_positives,
        result.false_negatives,
    )


if __name__ == "__main__":
    main()
