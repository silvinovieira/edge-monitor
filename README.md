# edge-monitor

Edge vibration monitoring in Python: simulated sensor with fault injection, bounded-memory
streaming anomaly detection, and a crash-safe disk queue syncing batches to S3
(LocalStack/moto).

## Architecture

```
 sensor ──MQTT──▶ processing ──▶ spool (disk) ──▶ sync ──▶ S3
```

Three independent services. **sensor** simulates an accelerometer on a vibrating
machine and streams samples with known fault windows. **processing** consumes the
stream in real time with a bounded rolling window, computes features, flags anomalies,
and writes compressed batches to an on-disk spool. **sync** uploads spooled batches to
S3, retrying with backoff when connectivity drops. Processing and sync run on the same
edge device as separate processes and share only the spool directory.

## Running it end to end

Requirements: Docker with Compose. One command starts the broker (mosquitto), S3
(LocalStack) and the three services:

```sh
docker compose up --build
```

What happens:

1. **sensor** publishes 1 kHz samples to MQTT in real time, in chunks of 50. A fault
   runs from 20 s to 30 s.
2. **processing** computes features 4 times a second, flags the fault, and writes a
   batch to the shared `spool` volume every 60 s.
3. **sync** uploads each batch to the `edge-monitor` bucket in LocalStack. About 10%
   of uploads fail on purpose, and every fifth minute is a simulated outage, so the
   logs show retries with backoff.

Follow it in the logs:

```sh
docker compose logs -f processing sync
```

An excerpt from a real run (timestamps shortened, sync's retry message in its current
wording). The first batch holds the fault at 20-30 s, a
random upload failure is retried, and the simulated outage at minute 4 makes sync back
off until the link returns:

```
processing  01:20:24 wrote 1792372764101182922_sensor-1.jsonl.gz (236 windows, 42 anomalous)
sync        01:20:24 uploaded vibration/v1/dt=2026-10-19/hour=01/sensor_id=sensor-1/1792372764101182922_sensor-1.jsonl.gz
processing  01:21:24 wrote 1792372824101182922_sensor-1.jsonl.gz (240 windows, 0 anomalous)
...
processing  01:24:24 wrote 1792373004101182922_sensor-1.jsonl.gz (240 windows, 0 anomalous)
sync        01:24:24 upload of 1792373004101182922_sensor-1.jsonl.gz failed: simulated outage
sync        01:24:24 failed 1 time(s) in a row; retrying in 0.6 s
sync        01:24:26 failed 3 time(s) in a row; retrying in 2.2 s
sync        01:24:28 failed 4 time(s) in a row; retrying in 7.5 s
sync        01:24:36 uploaded vibration/v1/dt=2026-10-19/hour=01/sensor_id=sensor-1/1792373004101182922_sensor-1.jsonl.gz
```

List what reached S3 (LocalStack accepts any credentials):

```sh
docker compose exec localstack awslocal s3 ls --recursive s3://edge-monitor/
```

Stop with `docker compose stop processing` first to see the evaluation summary.
Processing writes its last, shorter batch and logs precision and recall against the
ground truth:

```
processing  wrote 1792373064101182922_sensor-1.jsonl.gz (99 windows, 0 anomalous)
processing  dropped chunks: 0, invalid messages: 0, seq gaps: 0
processing  evaluation: precision 0.95, recall 1.00, F1 0.98, latency 0.50 s (TP 40, FP 2, FN 0)
```

That's the same result as the offline evaluation of seed 0 in
[processing/README.md](processing/README.md#evaluation). The sensor's default seed is 0,
and the pipeline is deterministic.

**Restarts.** `docker compose restart processing` loses nothing. Mosquitto queues the
messages while processing is down (persistent session). The restarted process
continues with new batch names, right after the last batch of the previous run, and
S3 ends up with exactly one object per batch. This was checked by hand: 5 batches
written across a restart, 5 objects in S3, and an empty spool.

Then `docker compose down` (add `-v` to delete the spool and broker volumes).

Each service also runs without Docker. See the service READMEs.

## Status

The project is built one feature at a time; the order is in [`docs/PLAN.md`](docs/PLAN.md).

| Service | What it does | Docs |
|---|---|---|
| sensor | Oscillator simulator with fault injection, published over MQTT in real time; `python -m sensor`. | [sensor/README.md](sensor/README.md) |
| processing | MQTT in; rolling window, features, anomaly detector and live evaluation; 60 s gzip JSONL batches written atomically to the spool; benchmark script; `python -m processing`. | [processing/README.md](processing/README.md) |
| sync | Uploads spooled batches to S3 oldest first, with idempotent keys, exponential backoff with full jitter, and simulated failures; `python -m sync`. | [sync/README.md](sync/README.md) |

## Repository layout

```
sensor/                    uv project: vibration sensor simulator
processing/                uv project: rolling window, features, anomaly detection
sync/                      uv project: spool → S3 uploader with retries
mosquitto/mosquitto.conf   minimal broker config for the local run
docker-compose.yml         the whole pipeline: mosquitto, LocalStack, three services
docs/
  PLAN.md                  feature order
  spool-contract.md        batch file format shared by processing and sync
  contract/fixtures/       sensor recordings that processing is tested against
  contract/example_batch.jsonl.gz   a real batch, checked against the contract
.github/workflows/ci.yml   ruff + pytest for each service
```

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if needed).
Each service is an independent uv project with its own dependencies and tests. Run the
checks from each service directory (`sensor`, `processing`, `sync`):

```sh
cd sensor
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

CI runs the same four commands for every service on each push to `main` and each pull
request.

## Design decisions and trade-offs

- **Independent services, no shared code.** Each service has its own `pyproject.toml`
  and lockfile, and never imports another service. They can be deployed, versioned and
  tested separately. The cost is some duplicated boilerplate (config loading, logging
  setup).
- **Recordings as the contract between sensor and processing.** Processing never
  imports the sensor, so it is tested against committed sensor output
  (`docs/contract/fixtures/`, 750 KB). The files are byte-for-byte reproducible from
  `sensor/scripts/make_fixtures.py`. The cost is regenerating them when the simulator
  changes.
- **A spool directory between processing and sync.** Processing writes complete
  batches into `ready/` with an atomic rename, and never talks to the network, so an
  S3 outage can't slow it down. The format is defined once in
  [`docs/spool-contract.md`](docs/spool-contract.md). The cost is disk space during
  outages (about 34 MB per sensor per day) and up to one minute of delay before data
  leaves the device.
- **At-least-once upload with idempotent S3 keys.** Sync deletes a batch only after S3
  confirms it, and the key is derived from the batch's deterministic file name. A
  crash or retry can upload a batch twice, but it overwrites the same object, so S3
  never holds duplicates. Keys are partitioned by event time
  (`vibration/v1/dt=…/hour=…/sensor_id=…/`), so late data lands where it belongs.
- **MQTT in chunks of 50 with QoS 1, and the ground truth on its own topic.** 20
  messages/s instead of 1000 keeps the protocol overhead small for at most 50 ms of
  latency. The truth topic keeps the detector honest: only the evaluator subscribes
  to it.
- **Bounded everywhere, and dropping before growing.** The rolling window, the MQTT
  queue (50 s), the sensor's outbound buffer (50 s) and each batch all have fixed
  sizes. Under pressure, the system drops the oldest data and counts the drops
  instead of using more memory. The cost is possible data loss in an extreme stall,
  which is visible in the logs.
- **Determinism everywhere.** All randomness goes through a seeded
  `numpy.random.Generator`, so every run and test is reproducible.
- **Python services with plain dependencies.** numpy, paho-mqtt and boto3 only. That
  keeps the images small and the code easy to follow. The cost is a per-sample Python
  loop in processing, which still runs about 440 times faster than real time.

## What's missing

- **A spool size cap.** If an outage lasts until the disk is full, writes fail
  (visible in the logs). The fix is a cap that evicts the oldest batches and counts
  the drops, sized from the measured 34 MB per sensor per day.
- **Quarantine for bad batches.** Sync logs and skips a batch it can't read, but
  leaves it in `ready/`, so the warning repeats on every pass. Moving such files to
  `corrupt/` would fix it.
- **Gap handling in the stream.** After a lost MQTT chunk, processing carries on as if
  the stream were contiguous, so later timestamps are early by the missing time.
  Inserting the missing samples (or restarting the time base) would fix it. With QoS 1
  and a persistent session it hasn't happened in testing.
- **A persistent detector baseline.** After a restart, processing learns its
  baseline again from the first 10 s. If it restarts during a fault, the fault is
  learned as normal and isn't flagged. Saving the frozen baseline to disk and loading
  it on start would fix that.
- **Lossless shutdown.** The few chunks still in processing's queue when it stops are
  lost, because they were already acknowledged to the broker. Acknowledging only after
  processing would fix it.
- **Sensitivity to small faults.** The detector reliably catches the default fault
  (resonance 50 → 65 Hz) but misses frequency shifts below about 8 Hz. Measurements
  and causes are in [processing/README.md](processing/README.md#evaluation).
- **Multiple faults or sensors in the live evaluation.** It scores the first fault of
  one sensor.
- **Production concerns:** TLS and authentication for MQTT, IAM roles for S3,
  non-root containers, health checks and metrics. These are out of scope for the
  prototype. The production section below discusses them.

## With more time

- **Better detection:** an EWMA or CUSUM on the peak frequency, or Welch-averaged
  spectra, compared against the current baseline using the existing evaluation. These
  trade latency for sensitivity to small shifts.
- **The missing items above,** starting with the spool cap, since running out of disk
  is the one failure that stops the pipeline.
- **A vectorised processing loop** (append whole chunks to the ring buffer with numpy
  slicing), if a slower edge CPU ever needs the headroom.
- **Smaller batches:** rounding floats to 6 significant digits halves the batch size
  (measured 23 → 11 KB).
- **An outage demo** (`make demo`) that pauses LocalStack and shows the spool growing
  and draining, instead of the manual check described in
  [sync/README.md](sync/README.md#how-failures-are-simulated).

## License

[MIT](LICENSE)
