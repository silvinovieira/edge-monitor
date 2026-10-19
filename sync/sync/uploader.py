"""Uploads one batch file to S3 under a key derived from its name."""

import gzip
import json
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from sync.config import SyncConfig

SUPPORTED_VERSION = 1
NS_PER_S = 1_000_000_000


class UploadError(Exception):
    """The upload failed; the batch stays in the spool and is retried."""


class InvalidBatchError(Exception):
    """The batch can't be uploaded as it is; retrying won't help."""


class Uploader(Protocol):
    def upload(self, path: Path) -> str: ...


def get_object_key(file_name: str) -> str:
    """Return the S3 key for a batch file, e.g.

    vibration/v1/dt=2026-01-01/hour=00/sensor_id=sensor-1/<file name>
    """
    try:
        start_ns, sensor_id = file_name.removesuffix(".jsonl.gz").split("_")
        start = datetime.fromtimestamp(int(start_ns) // NS_PER_S, UTC)
    except ValueError as error:
        raise InvalidBatchError(f"unexpected file name {file_name!r}") from error
    partition = f"dt={start:%Y-%m-%d}/hour={start:%H}/sensor_id={sensor_id}"
    return f"vibration/v1/{partition}/{file_name}"


def check_header(path: Path) -> None:
    """Reject batches this version of sync doesn't understand."""
    try:
        with gzip.open(path, "rt") as file:
            header = json.loads(file.readline())
    except (OSError, EOFError, zlib.error, json.JSONDecodeError) as error:
        raise InvalidBatchError(f"unreadable batch: {error}") from error
    if header.get("type") != "header":
        raise InvalidBatchError("first line is not a header")
    if header.get("version") != SUPPORTED_VERSION:
        raise InvalidBatchError(f"unsupported version {header.get('version')}")


class S3Uploader:
    def __init__(self, client: BaseClient, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def upload(self, path: Path) -> str:
        """Upload the batch and return its key."""
        key = get_object_key(path.name)
        check_header(path)
        try:
            # S3 checks the SHA256 on arrival and rejects a corrupted body.
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=path.read_bytes(),
                ContentType="application/gzip",
                ChecksumAlgorithm="SHA256",
            )
        except (BotoCoreError, ClientError) as error:
            raise UploadError(str(error)) from error
        return key


def make_s3_client(cfg: SyncConfig) -> BaseClient:
    # One attempt per call: the worker does the retrying, with its own backoff,
    # so outages show up in its logs instead of hiding inside boto3.
    client_config = Config(
        retries={"max_attempts": 1, "mode": "standard"},
        connect_timeout=5,
        read_timeout=10,
    )
    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url,
        region_name=cfg.region,
        config=client_config,
    )


def create_bucket(client: BaseClient, bucket: str, region: str) -> None:
    """Create the bucket unless it already exists."""
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError:
        pass
    # us-east-1 is the one region that rejects an explicit location.
    if region == "us-east-1":
        client.create_bucket(Bucket=bucket)
    else:
        client.create_bucket(
            Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region}
        )
