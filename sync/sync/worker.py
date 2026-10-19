"""Moves batches from the spool to S3, retrying with backoff while offline."""

import logging
import threading

import numpy as np

from sync.config import SyncConfig
from sync.spool_reader import SpoolReader
from sync.uploader import InvalidBatchError, Uploader, UploadError

log = logging.getLogger(__name__)

# 2**30 s is far beyond any cap; it only stops the exponent from overflowing.
MAX_BACKOFF_EXPONENT = 30


class Worker:
    def __init__(
        self,
        spool: SpoolReader,
        uploader: Uploader,
        cfg: SyncConfig,
        rng: np.random.Generator,
        stop: threading.Event,
    ) -> None:
        self._spool = spool
        self._uploader = uploader
        self._cfg = cfg
        self._rng = rng
        self._stop = stop
        self._failures = 0

    def run(self) -> None:
        """Upload until `stop` is set, waiting between passes and after failures."""
        log.info("watching %s", self._cfg.spool_dir / "ready")
        while not self._stop.is_set():
            if self.upload_pending():
                self._stop.wait(self._cfg.poll_s)
                continue
            self._failures += 1
            delay_s = self.get_backoff_s(self._failures)
            log.warning(
                "failed %d time(s) in a row; retrying in %.1f s",
                self._failures,
                delay_s,
            )
            # Event.wait instead of sleep, so a shutdown doesn't wait for it.
            self._stop.wait(delay_s)

    def upload_pending(self) -> bool:
        """Upload ready batches oldest first; return False at the first failure."""
        for path in self._spool.list_ready():
            if self._stop.is_set():
                break
            try:
                key = self._uploader.upload(path)
            except InvalidBatchError as error:
                # Retrying won't fix it, and it mustn't block the batches behind it.
                log.error("skipping %s: %s", path.name, error)
                continue
            except UploadError as error:
                log.warning("upload of %s failed: %s", path.name, error)
                return False
            # Delete only after S3 confirmed the upload. A crash between the two
            # re-uploads the batch under the same key: at-least-once, no duplicates.
            self._spool.remove(path)
            self._failures = 0
            log.info("uploaded %s", key)
        return True

    def get_backoff_s(self, failures: int) -> float:
        """Exponential backoff with full jitter, capped."""
        exponent = min(failures - 1, MAX_BACKOFF_EXPONENT)
        ceiling = min(self._cfg.backoff_cap_s, self._cfg.backoff_base_s * 2**exponent)
        # A random wait below the ceiling, so many devices that lose the link
        # together don't all retry at the same moment when it comes back.
        return float(self._rng.uniform(0, ceiling))
