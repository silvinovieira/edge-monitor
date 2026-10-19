import shutil
from pathlib import Path

import boto3
import pytest
from helpers import BUCKET, EXAMPLE_BATCH
from moto import mock_aws


@pytest.fixture
def s3(monkeypatch):
    """An in-memory S3 (moto) with one empty bucket."""
    # Fake credentials, so nothing can ever reach real AWS.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def spool_dir(tmp_path) -> Path:
    """A spool with three batches in ready/, one minute apart."""
    ready = tmp_path / "ready"
    ready.mkdir()
    for minute in range(3):
        start_ns = 1_767_225_600_000_000_000 + minute * 60_000_000_000
        shutil.copy(EXAMPLE_BATCH, ready / f"{start_ns}_sensor-1.jsonl.gz")
    return tmp_path
