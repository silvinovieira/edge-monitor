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

## Status

The project is built one feature at a time; the order is in [`docs/PLAN.md`](docs/PLAN.md).

| Service | Today | Docs |
|---|---|---|
| sensor | Oscillator simulator with fault injection; `python -m sensor.simulator` prints one second of samples. MQTT publishing not yet built. | [sensor/README.md](sensor/README.md) |
| processing | Rolling window, features, anomaly detector and evaluation over any stream of sample chunks; benchmark script. MQTT input and spool output not yet built. | [processing/README.md](processing/README.md) |
| sync | Not yet built. | |

## Repository layout

```
sensor/                    uv project: vibration sensor simulator
processing/                uv project: rolling window, features, anomaly detection
docs/
  PLAN.md                  feature order
  contract/fixtures/       sensor recordings that processing is tested against
.github/workflows/ci.yml   ruff + pytest for each service
```

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if needed).
Each service is an independent uv project with its own dependencies and tests. Run the
checks from each service directory (`sensor`, `processing`):

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
- **Determinism everywhere.** All randomness goes through a seeded
  `numpy.random.Generator`, so every run and test is reproducible.

## License

[MIT](LICENSE)
