"""Run the sensor: python -m sensor (simulate and publish over MQTT)."""

import logging
import signal
import threading
import time

import paho.mqtt.client as mqtt

from sensor.config import SensorConfig
from sensor.publisher import (
    encode,
    get_samples_topic,
    get_truth_topic,
    make_sample_messages,
    make_truth_message,
    publish_in_real_time,
)
from sensor.simulator import get_fault_ranges, simulate

log = logging.getLogger("sensor")

# paho buffers messages while the broker is unreachable; cap it so a long
# outage can't grow memory without bound (1000 chunks = 50 s of data).
MAX_QUEUED_MESSAGES = 1000


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = SensorConfig.from_env()
    stop = threading.Event()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signal_number, lambda *_: stop.set())

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"sensor-{cfg.sensor_id}"
    )
    client.max_queued_messages_set(MAX_QUEUED_MESSAGES)
    # connect_async + loop_start: paho connects and reconnects in the background,
    # so a broker that starts later or restarts doesn't stop the sensor.
    client.connect_async(cfg.mqtt_host, cfg.mqtt_port)
    client.loop_start()

    faults = [cfg.default_fault()]
    fault_ranges = [samples for samples, _ in get_fault_ranges(cfg, faults)]
    truth = encode(make_truth_message(fault_ranges))
    client.publish(get_truth_topic(cfg.sensor_id), truth, qos=1, retain=True)
    log.info("publishing to %s:%d, truth %s", cfg.mqtt_host, cfg.mqtt_port, truth)

    samples_topic = get_samples_topic(cfg.sensor_id)

    def publish(message: dict) -> None:
        info = client.publish(samples_topic, encode(message), qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning(
                "dropped chunk %d: %s", message["seq"], mqtt.error_string(info.rc)
            )
        elif message["seq"] % 200 == 0:  # every 10 s
            log.info("published chunk %d", message["seq"])

    messages = make_sample_messages(
        simulate(cfg, faults), cfg.sensor_id, cfg.sample_rate_hz, time.time_ns()
    )
    publish_in_real_time(messages, publish, time.time_ns, stop.wait)
    client.loop_stop()
    client.disconnect()
    log.info("stopped")


if __name__ == "__main__":
    main()
