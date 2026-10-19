"""Reads complete batches from the spool (format: docs/spool-contract.md)."""

from pathlib import Path


class SpoolReader:
    def __init__(self, spool_dir: Path) -> None:
        # Only ready/ holds complete files; tmp/ belongs to the writer.
        self._ready_dir = spool_dir / "ready"

    def list_ready(self) -> list[Path]:
        """Return the batches waiting for upload, oldest first."""
        if not self._ready_dir.exists():
            return []
        # File names start with a zero-padded timestamp, so name order is time order.
        return sorted(self._ready_dir.glob("*.jsonl.gz"))

    def remove(self, path: Path) -> None:
        """Delete exactly this batch, after it has been uploaded."""
        if path.parent != self._ready_dir:
            raise ValueError(f"{path} is not in {self._ready_dir}")
        # No directory fsync: if a power cut undoes the delete, the batch is
        # uploaded again under the same key, which changes nothing.
        path.unlink()
