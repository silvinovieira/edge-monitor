"""Run the simulator and write samples as CSV to stdout.

    uv run python -m sensor --seconds 2 > samples.csv

Configuration comes from the SENSOR_* environment variables. Samples go to stdout
as data; diagnostics go to stderr through logging, so the two never mix.
"""

import argparse
import csv
import logging
import sys
from itertools import islice

from sensor.config import SensorConfig
from sensor.simulator import simulate

log = logging.getLogger("sensor")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m sensor", description=__doc__)
    parser.add_argument(
        "--seconds",
        type=float,
        default=1.0,
        help="stream time to simulate (default: 1.0)",
    )
    parser.add_argument(
        "--no-fault", action="store_true", help="run at baseline, without the fault"
    )
    args = parser.parse_args(argv)
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    return args


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    cfg = SensorConfig.from_env()
    faults = [] if args.no_fault else [cfg.default_fault()]
    sample_count = round(args.seconds * cfg.sample_rate_hz)
    log.info("simulating %d samples; config=%s faults=%s", sample_count, cfg, faults)

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["t", "accel", "in_fault"])
    for sample in islice(simulate(cfg, faults), sample_count):
        writer.writerow(
            [f"{sample.t:.3f}", f"{sample.accel:.6f}", int(sample.in_fault)]
        )


if __name__ == "__main__":
    main()
