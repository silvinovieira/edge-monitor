"""Writes batches into the on-disk spool so that a crash never leaves a partial file.

Layout (see docs/spool-contract.md): files are written in `tmp/` and moved
into `ready/` only when complete; the sync service reads only `ready/`.
"""

import gzip
import json
import logging
import os
from pathlib import Path

from processing.batcher import Batch

log = logging.getLogger(__name__)


def encode_batch(batch: Batch) -> bytes:
    """Return the batch as gzip-compressed JSON lines."""
    text = "".join(
        json.dumps(line, separators=(",", ":")) + "\n" for line in batch.lines
    )
    # mtime=0 keeps the bytes identical for identical batches.
    return gzip.compress(text.encode(), mtime=0)


class SpoolWriter:
    def __init__(self, spool_dir: Path) -> None:
        self._tmp_dir = spool_dir / "tmp"
        self._ready_dir = spool_dir / "ready"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        self._ready_dir.mkdir(parents=True, exist_ok=True)
        self._remove_unfinished_files()

    def write(self, batch: Batch) -> Path:
        """Write the batch atomically and durably; return its path in `ready/`."""
        tmp_path = self._tmp_dir / batch.file_name
        with open(tmp_path, "wb") as file:
            file.write(encode_batch(batch))
            file.flush()
            os.fsync(file.fileno())
        ready_path = self._ready_dir / batch.file_name
        # The rename is atomic: readers see the whole file or no file.
        os.replace(tmp_path, ready_path)
        # Persist the rename itself, or a power cut could undo it.
        _fsync_directory(self._ready_dir)
        return ready_path

    def _remove_unfinished_files(self) -> None:
        # Anything left in tmp/ was cut off by a crash before its rename.
        for path in self._tmp_dir.iterdir():
            log.warning("removing unfinished spool file %s", path.name)
            path.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
