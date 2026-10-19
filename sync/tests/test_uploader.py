import gzip
import shutil

import pytest
from helpers import BUCKET, EXAMPLE_BATCH, EXAMPLE_NAME, list_keys

from sync.uploader import (
    InvalidBatchError,
    S3Uploader,
    UploadError,
    create_bucket,
    get_object_key,
)

EXAMPLE_KEY = (
    "vibration/v1/dt=2026-01-01/hour=00/sensor_id=sensor-1/"
    "1767225600000000000_sensor-1.jsonl.gz"
)


def test_key_comes_from_the_file_name():
    assert get_object_key(EXAMPLE_NAME) == EXAMPLE_KEY


def test_key_uses_the_batch_start_hour():
    # 2026-01-01T13:59:59Z
    name = "1767275999000000000_pump-7.jsonl.gz"
    assert get_object_key(name) == (
        f"vibration/v1/dt=2026-01-01/hour=13/sensor_id=pump-7/{name}"
    )


@pytest.mark.parametrize(
    "name", ["batch.jsonl.gz", "abc_sensor-1.jsonl.gz", "1_2_3.jsonl.gz"]
)
def test_unexpected_file_names_are_invalid(name):
    with pytest.raises(InvalidBatchError):
        get_object_key(name)


def test_uploads_the_contract_example(s3, tmp_path):
    path = tmp_path / EXAMPLE_NAME
    shutil.copy(EXAMPLE_BATCH, path)
    assert S3Uploader(s3, BUCKET).upload(path) == EXAMPLE_KEY
    stored = s3.get_object(Bucket=BUCKET, Key=EXAMPLE_KEY, ChecksumMode="ENABLED")
    assert stored["Body"].read() == EXAMPLE_BATCH.read_bytes()
    assert "ChecksumSHA256" in stored


def test_uploading_the_same_file_twice_leaves_one_object(s3, tmp_path):
    path = tmp_path / EXAMPLE_NAME
    shutil.copy(EXAMPLE_BATCH, path)
    uploader = S3Uploader(s3, BUCKET)
    uploader.upload(path)
    uploader.upload(path)
    assert list_keys(s3) == [EXAMPLE_KEY]


def test_unsupported_version_is_rejected(s3, tmp_path):
    path = tmp_path / EXAMPLE_NAME
    path.write_bytes(gzip.compress(b'{"type":"header","version":2}\n'))
    with pytest.raises(InvalidBatchError, match="version 2"):
        S3Uploader(s3, BUCKET).upload(path)
    assert list_keys(s3) == []


def test_unreadable_file_is_rejected(s3, tmp_path):
    path = tmp_path / EXAMPLE_NAME
    path.write_bytes(b"not gzip")
    with pytest.raises(InvalidBatchError):
        S3Uploader(s3, BUCKET).upload(path)


def test_s3_errors_become_upload_errors(s3, tmp_path):
    path = tmp_path / EXAMPLE_NAME
    shutil.copy(EXAMPLE_BATCH, path)
    with pytest.raises(UploadError):
        S3Uploader(s3, "no-such-bucket").upload(path)


def test_create_bucket_is_idempotent(s3):
    create_bucket(s3, "new-bucket", "us-east-1")
    create_bucket(s3, "new-bucket", "us-east-1")
    create_bucket(s3, BUCKET, "us-east-1")
    names = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    assert sorted(names) == ["new-bucket", BUCKET]
