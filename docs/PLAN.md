# Feature plan

One branch and one PR per feature, in this order. Each feature introduces only what it
uses. Every PR passes ruff and pytest in CI and updates the README.
PR description headings: What and why, How to test, Key decisions, Not included,
Talking points.

---

## 1. `feat/sensor-simulator`
**Introduces:** `sensor/` uv project (Python 3.12; numpy; dev: pytest, ruff),
`.github/workflows/ci.yml` (matrix: `sensor`; runs `uv sync`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run pytest -q`).

**Build**
- `sensor/sensor/config.py`: frozen dataclass from env vars. Defaults: `fs=1000`,
  `f_n_hz=50`, `zeta=0.05`, `noise_std=1.0`, `seed=0`, fault `start=20`, `duration=10`,
  `omega_scale=1.3`, `zeta_scale=0.5`.
- `sensor/sensor/simulator.py`: `Sample(t, accel, in_fault)`;
  `simulate(cfg, faults) -> Iterator[Sample]`.
  - RK4 on `[x, v]`, `dt = 1/fs`; `F ~ N(0, noise_std)` drawn once per step, held
    constant across the 4 stages.
  - Fault windows half-open `[start, start + duration)`; inside, scale `omega` and `zeta`.
  - Output `a = F - 2*zeta*omega*v - omega**2 * x`.
- `sensor/scripts/make_fixtures.py`: seeds 0-4, 40 s each, `.npz` (accel float32 +
  fault windows) to `docs/contract/fixtures/`. Commit the fixtures.

**Tests:** same seed → identical output; FFT peak ≈ 50 Hz at baseline, ≈ 65 Hz in the
fault; `in_fault` true exactly in `[20, 30)`.

**README:** project overview (three services, one paragraph); repository layout;
how to run the tests; sensor model (equation, parameters, fault injection, assumptions).

## 2. `feat/processing-core`
**Introduces:** `processing/` uv project (numpy; dev: pytest, ruff); `processing` added
to CI matrix.

**Build** (in `processing/processing/`)
- `ring_buffer.py`: preallocated numpy ring, capacity 1024, O(1) append, chronological
  `snapshot()`.
- `features.py`: RMS, mean, std, dominant frequency (Hann → rfft → skip DC → parabolic
  interpolation); every 250 samples once the buffer is full.
- `detector.py`: 10 s warm-up learns mean/std per feature (Welford), then frozen;
  anomaly after 2 consecutive windows with any |z| > 4. Never receives ground truth.
- `evaluate.py`: overlap labels (≥ 0.5 positive, 0 negative, else boundary, reported
  separately); precision, recall, F1, detection latency, false alarms per hour.
- `processor.py`: loop over an iterator of sample chunks → buffer → features → detector;
  outputs window results to a sink interface.
- `processing/scripts/benchmark.py`: throughput (samples/s) and memory (tracemalloc peak,
  RSS start and end) over 10 simulated minutes from the fixtures.

**Tests:** ring buffer bounded after 1M appends ★; features on a pure sine; no
look-ahead; detector on the fixtures: mean precision and recall ≥ 0.8, latency < 1.5 s,
fault detected on every seed ★.

**README:** processing design (window, hop, features, detector, no look-ahead);
evaluation method and results per seed (honest, including weak spots); measured
throughput and memory footprint; how to run the benchmark.

## 3. `feat/processing-batcher`
**Introduces:** `docs/spool-contract.md`, `docs/contract/example_batch.jsonl.gz`.

**Build** (in `processing/processing/`)
- `downsample.py`: every 100 samples, mean and RMS (10 Hz).
- `batcher.py`: implements the sink; collects windows + 10 Hz points; flushes every
  60 s of stream time and on shutdown.
- `spool_writer.py`: atomic write (tmp → flush → fsync → os.replace → fsync dir);
  file name `{start_ts_ns}_{seq:08d}_{uuid8}.jsonl.gz`; removes orphan `tmp/` files on
  startup; size cap evicts oldest in `ready/` and counts drops.
- `docs/spool-contract.md`: directories, file naming, gzip JSONL schema (`header`,
  `window` lines, one `samples_10hz` line), versioning rule.
- Generate the example batch with the real batcher (script), commit it.

**Tests:** output matches the contract; restart leaves no `tmp/` files; size cap evicts
oldest and counts drops.

**README:** batch format and why (JSONL + gzip vs Parquet, 60 s vs per window); spool
durability (atomic writes, fsync); disk cap policy and sizing (bytes/s × outage ×
safety factor).

## 4. `feat/sync-worker`
**Introduces:** `sync/` uv project (boto3; dev: pytest, ruff, moto[s3]); `sync` added to
CI matrix.

**Build** (in `sync/sync/`)
- `spool_reader.py`: lists `ready/` oldest first; quarantines unreadable files in
  `corrupt/`; removes exactly the given path.
- `uploader.py`: key `vibration/v1/dt=YYYY-MM-DD/hour=HH/sensor_id=<id>/<file name>`
  from batch start time; `endpoint_url` configurable; SHA256 checksum.
- `faults.py`: `FlakyUploader` (seeded random failures + scheduled outages).
- `worker.py`: upload → on success remove that file → reset backoff; on failure
  exponential backoff with full jitter (base 1 s, cap 60 s) via `Event.wait`.
- `__main__.py`: runs the worker against a spool directory.

**Tests (moto):** reads the contract example; restart: batches survive a failing
uploader, new worker uploads every batch exactly once, spool empty ★; re-uploading the
same file leaves one object.

**README:** S3 layout and justification (event time, partition order, alternative);
delivery guarantees (at-least-once + idempotent keys = no duplicates); retry and backoff;
how failures are simulated.

## 5. `feat/sensor-mqtt`
**Introduces:** paho-mqtt in sensor; `docker-compose.yml` with `mosquitto`
(eclipse-mosquitto 2, port 1883, minimal config) and `sensor`; `sensor/Dockerfile`
(python:3.12-slim + uv).

**Build**
- `sensor/sensor/publisher.py`: real-time pacing with absolute deadlines; chunks of 50
  samples to `sensors/<id>/samples` (QoS 1, JSON `{sensor_id, seq, t0, dt, values}`);
  truth to `sensors/<id>/truth` (`{seq, in_fault}`).

**Tests:** chunking and message format with a fake MQTT client.

**README:** MQTT design (chunks, QoS, separate truth topic and why); how to run the
sensor and broker with compose.

## 6. `feat/processing-mqtt`
**Introduces:** paho-mqtt in processing; `processing/Dockerfile`; `processing` service in
compose; shared `spool` volume.

**Build** (in `processing/processing/`)
- `subscriber.py`: paho callback → bounded `queue.Queue`; if full, drop oldest and count;
  log `seq` gaps. Truth subscription only when evaluation is enabled.
- `__main__.py`: subscriber → processor → batcher → spool writer; live evaluation
  summary at shutdown when enabled.

**Tests:** subscriber with a fake client; queue drop behaviour.

**README:** running sensor → processing; backpressure policy; memory of the running
container and how to verify it on constrained hardware (cgroup limits, VmHWM).

## 7. `feat/sync-localstack`
**Introduces:** `localstack` (S3 only, port 4566) and `sync` in compose;
`sync/Dockerfile`; `Makefile` (`up`, `down`, `test`, `demo`).

**Build**
- Sync service mounts the shared spool volume and uploads to LocalStack.
- `make demo`: runs everything, triggers an outage, shows the spool growing and draining.

**Tests:** existing tests stay green; demo checked by hand.

**README:** end-to-end run (sensor → processing → sync); the outage demo; key trade-offs
and what would change with more time; what's missing; "From prototype to production edge
deployment" (systemd vs Greengrass, OTA with rollback, observability over intermittent
links, sizing for real hardware).
