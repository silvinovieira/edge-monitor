"""Run the sync worker: python -m sync"""

import logging
import signal
import threading

import numpy as np
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

from sync.config import SyncConfig
from sync.faults import FlakyUploader
from sync.spool_reader import SpoolReader
from sync.uploader import S3Uploader, create_bucket, make_s3_client
from sync.worker import Worker

log = logging.getLogger("sync")

BUCKET_RETRY_S = 5.0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = SyncConfig.from_env()
    stop = threading.Event()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signal_number, lambda *_: stop.set())

    client = make_s3_client(cfg)
    if cfg.create_bucket:
        _create_bucket_when_reachable(client, cfg, stop)
    rng = np.random.default_rng(cfg.seed)
    uploader = FlakyUploader(
        S3Uploader(client, cfg.bucket),
        cfg.failure_rate,
        cfg.outage_every_s,
        cfg.outage_s,
        rng,
    )
    Worker(SpoolReader(cfg.spool_dir), uploader, cfg, rng, stop).run()
    log.info("stopped")


def _create_bucket_when_reachable(
    client: BaseClient, cfg: SyncConfig, stop: threading.Event
) -> None:
    # S3 may not be up yet when the device boots; keep trying instead of crashing.
    while not stop.is_set():
        try:
            create_bucket(client, cfg.bucket, cfg.region)
            return
        except (BotoCoreError, ClientError) as error:
            log.warning("can't create bucket %s yet: %s", cfg.bucket, error)
            stop.wait(BUCKET_RETRY_S)


if __name__ == "__main__":
    main()
