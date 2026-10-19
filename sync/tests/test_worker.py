import threading
from pathlib import Path

import numpy as np
from helpers import BUCKET, list_keys

from sync.config import SyncConfig
from sync.spool_reader import SpoolReader
from sync.uploader import S3Uploader, UploadError
from sync.worker import Worker

CFG = SyncConfig(backoff_base_s=1.0, backoff_cap_s=60.0)


class AlwaysFails:
    def upload(self, path: Path) -> str:
        raise UploadError("network down")


class CountingUploader:
    """Records every upload it passes on, to prove nothing is sent twice."""

    def __init__(self, uploader) -> None:
        self._uploader = uploader
        self.uploaded: list[str] = []

    def upload(self, path: Path) -> str:
        self.uploaded.append(path.name)
        return self._uploader.upload(path)


def _make_worker(spool_dir: Path, uploader) -> Worker:
    return Worker(
        SpoolReader(spool_dir),
        uploader,
        CFG,
        np.random.default_rng(0),
        threading.Event(),
    )


def test_batches_survive_a_restart_and_are_uploaded_exactly_once(s3, spool_dir):
    names = sorted(path.name for path in (spool_dir / "ready").iterdir())

    # First run: the network is down, so every batch must stay on disk.
    assert not _make_worker(spool_dir, AlwaysFails()).upload_pending()
    assert sorted(path.name for path in (spool_dir / "ready").iterdir()) == names

    # Restart: a brand-new worker, reading only what is on disk.
    counting = CountingUploader(S3Uploader(s3, BUCKET))
    assert _make_worker(spool_dir, counting).upload_pending()

    assert counting.uploaded == names  # each batch once, oldest first
    assert len(list_keys(s3)) == len(names)
    assert list((spool_dir / "ready").iterdir()) == []


def test_failure_stops_the_pass_and_keeps_the_rest(s3, spool_dir):
    class FailsOnSecond:
        def __init__(self) -> None:
            self.calls = 0

        def upload(self, path: Path) -> str:
            self.calls += 1
            if self.calls == 2:
                raise UploadError("link dropped")
            return S3Uploader(s3, BUCKET).upload(path)

    assert not _make_worker(spool_dir, FailsOnSecond()).upload_pending()
    assert len(list_keys(s3)) == 1
    assert len(list((spool_dir / "ready").iterdir())) == 2


def test_invalid_batch_is_skipped_not_blocking(s3, spool_dir):
    oldest = SpoolReader(spool_dir).list_ready()[0]
    oldest.write_bytes(b"corrupted")
    assert _make_worker(spool_dir, S3Uploader(s3, BUCKET)).upload_pending()
    assert len(list_keys(s3)) == 2
    assert SpoolReader(spool_dir).list_ready() == [oldest]


def test_backoff_grows_exponentially_up_to_the_cap(tmp_path):
    worker = _make_worker(tmp_path, AlwaysFails())
    for failures, ceiling in [(1, 1), (2, 2), (3, 4), (7, 60), (10_000, 60)]:
        delays = [worker.get_backoff_s(failures) for _ in range(500)]
        assert 0 <= min(delays) and max(delays) <= ceiling
        assert max(delays) > 0.8 * ceiling  # full jitter spans the whole range


def test_run_stops_promptly_when_asked(spool_dir):
    stop = threading.Event()
    worker = Worker(
        SpoolReader(spool_dir), AlwaysFails(), CFG, np.random.default_rng(0), stop
    )
    thread = threading.Thread(target=worker.run)
    thread.start()
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
