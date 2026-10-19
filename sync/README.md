# sync

Uploads the batches that processing leaves in the spool to S3, oldest first. During
outages it retries with exponential backoff, and batches stay on disk until S3 has
confirmed them, so nothing is lost across a restart. By default it also simulates bad
connectivity, so the retry path is exercised all the time.

## Installation

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
cd sync
uv sync
```

Dependencies:
- **boto3**: the S3 client.
- **numpy**: only for its seeded `numpy.random.Generator`, which draws the backoff
  jitter and the simulated failures. The project allows randomness only through a
  seeded generator, so runs and tests are reproducible. numpy is already a dependency
  of the other two services.

## Usage

Against LocalStack (S3 on port 4566), with a spool written by processing:

```sh
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
SYNC_SPOOL_DIR=../processing/spool \
SYNC_ENDPOINT_URL=http://localhost:4566 SYNC_CREATE_BUCKET=true \
uv run python -m sync
```

It runs until SIGTERM or Ctrl-C. An upload in progress finishes or times out first, so
stopping during an outage can take up to about 20 s. Typical log output, with
simulated failures on:

```
INFO sync.worker: uploaded vibration/v1/dt=2026-01-01/hour=00/sensor_id=sensor-1/1767225660000000000_sensor-1.jsonl.gz
WARNING sync.worker: upload of 1767225720000000000_sensor-1.jsonl.gz failed: simulated failure
WARNING sync.worker: 1 failures in a row; retrying in 0.9 s
INFO sync.worker: uploaded vibration/v1/dt=2026-01-01/hour=00/sensor_id=sensor-1/1767225720000000000_sensor-1.jsonl.gz
```

## Configuration

`SyncConfig.from_env()` reads these environment variables into a frozen dataclass:

| Variable | Default | Meaning |
|---|---|---|
| `SYNC_SPOOL_DIR` | spool | spool directory, shared with processing |
| `SYNC_BUCKET` | edge-monitor | S3 bucket |
| `SYNC_ENDPOINT_URL` | (unset) | unset means real AWS; `http://localhost:4566` for LocalStack |
| `SYNC_REGION` | us-east-1 | AWS region |
| `SYNC_CREATE_BUCKET` | false | create the bucket at start (LocalStack only) |
| `SYNC_POLL_S` | 1 | wait between passes when the spool is empty (s) |
| `SYNC_BACKOFF_BASE_S` | 1 | first backoff ceiling (s) |
| `SYNC_BACKOFF_CAP_S` | 60 | largest backoff ceiling (s) |
| `SYNC_FAILURE_RATE` | 0.1 | probability that an upload fails (simulated) |
| `SYNC_OUTAGE_EVERY_S` | 300 | length of one outage cycle (s) |
| `SYNC_OUTAGE_S` | 60 | outage at the end of each cycle (s); 0 turns it off |
| `SYNC_SEED` | 0 | seed for jitter and simulated failures |

Credentials come from the usual AWS sources (environment, profile, instance role).

## S3 layout

```
s3://edge-monitor/vibration/v1/dt=2026-01-01/hour=00/sensor_id=sensor-1/1767225600000000000_sensor-1.jsonl.gz
                  └ dataset  └ layout   └ partitions (Hive style)          └ spool file name, unchanged
                             version
```

- **Derived from the file name only.** The key is a pure function of the batch's
  name, which processing makes deterministic. Uploading the same batch again, after a
  retry or a crash, overwrites the same object instead of adding a duplicate.
- **Event time, not upload time.** `dt` and `hour` come from the batch's first sample
  (the timestamp in the name), not from when it was uploaded. A batch delayed by a
  two-day outage still lands in the hour it describes, so queries over a time range
  find it, and backfilled data never looks like new data.
- **Hive-style `key=value` partitions.** Athena, Glue and Spark recognise them without
  configuration and skip partitions a query doesn't need. Most questions are about a
  time range across the fleet ("anomalies yesterday"), so time comes first: such a
  query reads one `dt=` prefix. `hour` keeps a single partition to 60 files per sensor.
- **`v1` in the key.** If the layout or format ever changes incompatibly, new data
  goes to `v2/` next to the old data, and readers choose which to read.
- **Alternative:** `sensor_id` first (`sensor_id=…/dt=…/hour=…`) makes "everything
  from one sensor" cheap and suits fleets where analysis is mostly per machine. Its
  cost is that time-range queries across sensors must list every sensor's prefix. With
  a fleet-wide view as the main use, time first is the better default. Per-sensor
  access can still filter on the `sensor_id` partition.

## Delivery guarantees

**At-least-once upload with idempotent keys, so no duplicates in S3.** The worker
deletes a batch from `ready/` only after `put_object` has returned successfully:

- **Crash before the upload finishes:** the batch is still on disk, and the next run
  uploads it.
- **Crash after the upload but before the delete:** the next run uploads it again,
  under the same key, so S3 still holds one object.
- **Delete undone by a power cut:** the same re-upload happens. That's why the delete
  doesn't need a directory fsync.

It deletes exactly the file it uploaded, by path, never "the oldest". Batches are
uploaded oldest first. Each upload carries a SHA256 checksum that S3 verifies on
arrival, so a body corrupted in transit is rejected and retried. A batch that can't
be uploaded as it is (unreadable, or an unknown format `version`) is logged and
skipped, and stays in `ready/`. It doesn't block the batches behind it.

## Retry and backoff

- After a failure the pass stops, and the worker waits before trying the oldest batch
  again. The wait is drawn uniformly from `[0, ceiling]`, where the ceiling is
  `min(60 s, 1 s × 2^(failures − 1))`: 1, 2, 4, 8 … 60 s. This is "full jitter". Many
  devices that lose the same link would otherwise all retry at the same moment when it
  comes back.
- The first success resets the count.
- Waits use `threading.Event.wait`, so a shutdown signal ends them at once.
- boto3's own retries are turned off (one attempt per call, 5 s connect and 10 s read
  timeouts). All retrying happens here, where it is logged, instead of silently inside
  each call.

## How failures are simulated

`FlakyUploader` wraps the real uploader and fails some uploads before they start:
- **random failures:** each upload fails with probability `SYNC_FAILURE_RATE`
  (default 10%), drawn from the seeded generator, so a given seed always fails the
  same uploads
- **scheduled outages:** for the last `SYNC_OUTAGE_S` of every `SYNC_OUTAGE_EVERY_S`
  period (default 60 s out of every 5 minutes), every upload fails, like a cellular
  link that drops regularly

A real outage was also checked by hand. I paused a LocalStack container and ran sync
until it timed out on the upload. I stopped it, resumed LocalStack, and started a new
sync process. All three batches had stayed in `ready/`, the new process uploaded each
one once, and the spool ended empty.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The tests run against an in-memory S3 ([moto](https://github.com/getmoto/moto)), with
no Docker and no network. They cover:
- the durable queue surviving a restart: a first worker fails every upload and all
  batches stay on disk; a new worker then uploads each batch exactly once, oldest
  first, and the spool ends empty
- uploading the contract's example batch to the expected key, with its SHA256
  checksum, and re-uploading it without creating a second object
- a failure stopping the pass without losing the remaining batches, and an invalid
  batch being skipped without blocking the rest
- rejecting unsupported versions, unreadable files and unexpected file names
- backoff bounds and full jitter, a prompt stop, and the simulated faults (rate,
  seed, outage schedule)
- the spool reader: oldest first, `tmp/` ignored, deleting exactly one path
- reading the configuration from the environment
