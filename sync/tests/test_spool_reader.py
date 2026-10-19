import pytest

from sync.spool_reader import SpoolReader


def test_lists_ready_batches_oldest_first(tmp_path):
    (tmp_path / "ready").mkdir()
    (tmp_path / "tmp").mkdir()
    for name in ["0000000000000000002_a.jsonl.gz", "0000000000000000001_a.jsonl.gz"]:
        (tmp_path / "ready" / name).write_bytes(b"")
    (tmp_path / "tmp" / "0000000000000000000_a.jsonl.gz").write_bytes(b"")
    names = [path.name for path in SpoolReader(tmp_path).list_ready()]
    assert names == ["0000000000000000001_a.jsonl.gz", "0000000000000000002_a.jsonl.gz"]


def test_missing_spool_has_nothing_ready(tmp_path):
    assert SpoolReader(tmp_path / "nowhere").list_ready() == []


def test_remove_deletes_exactly_that_file(spool_dir):
    reader = SpoolReader(spool_dir)
    first, second, third = reader.list_ready()
    reader.remove(second)
    assert reader.list_ready() == [first, third]


def test_remove_refuses_files_outside_ready(spool_dir):
    outside = spool_dir / "other.jsonl.gz"
    outside.write_bytes(b"")
    with pytest.raises(ValueError):
        SpoolReader(spool_dir).remove(outside)
    assert outside.exists()
