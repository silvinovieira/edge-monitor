import gzip
import json

import pytest

from processing.batcher import Batch
from processing.spool_writer import SpoolWriter, encode_batch

BATCH = Batch(
    file_name="1767225600000000000_sensor-1.jsonl.gz",
    lines=[{"type": "header", "version": 1}, {"type": "window", "rms": 1.5}],
)


def _read_lines(path) -> list[dict]:
    return [
        json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()
    ]


def test_write_puts_the_complete_file_in_ready(tmp_path):
    path = SpoolWriter(tmp_path).write(BATCH)
    assert path == tmp_path / "ready" / BATCH.file_name
    assert _read_lines(path) == BATCH.lines
    assert list((tmp_path / "tmp").iterdir()) == []


def test_same_batch_gives_same_bytes():
    assert encode_batch(BATCH) == encode_batch(BATCH)


def test_crash_before_rename_leaves_nothing_in_ready(tmp_path, monkeypatch):
    def crash(*args):
        raise OSError("power cut")

    monkeypatch.setattr("processing.spool_writer.os.replace", crash)
    with pytest.raises(OSError):
        SpoolWriter(tmp_path).write(BATCH)
    assert list((tmp_path / "ready").iterdir()) == []
    assert [p.name for p in (tmp_path / "tmp").iterdir()] == [BATCH.file_name]


def test_restart_removes_unfinished_files(tmp_path):
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / BATCH.file_name).write_bytes(b"half a fi")
    SpoolWriter(tmp_path)
    assert list((tmp_path / "tmp").iterdir()) == []


def test_restart_keeps_finished_files(tmp_path):
    path = SpoolWriter(tmp_path).write(BATCH)
    SpoolWriter(tmp_path)
    assert path.exists()
