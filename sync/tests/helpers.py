"""Constants and helpers shared by the tests."""

from pathlib import Path

EXAMPLE_BATCH = (
    Path(__file__).resolve().parents[2] / "docs" / "contract" / "example_batch.jsonl.gz"
)
EXAMPLE_NAME = "1767225600000000000_sensor-1.jsonl.gz"
BUCKET = "test-bucket"


def list_keys(s3) -> list[str]:
    return [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])]
