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
| sensor | Oscillator simulator with fault injection, as a Python generator. MQTT publishing not yet built. | [sensor/README.md](sensor/README.md) |
| processing | Not yet built. | |
| sync | Not yet built. | |

## Repository layout

```
sensor/                    uv project: vibration sensor simulator
docs/
  PLAN.md                  feature order
  contract/fixtures/       shared test data (seed_{0..4}.npz)
.github/workflows/ci.yml   ruff + pytest for each service
```

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if needed).
Each service is an independent uv project with its own dependencies and tests. Run the
checks from the service directory:

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
- **Shared files are the contract.** The only things services share are files under
  `docs/contract/`. Today that's the simulator fixtures, which give the processing tests
  deterministic input without importing the sensor. Any change to those files must
  update their consumers in the same change.
- **Determinism everywhere.** All randomness goes through a seeded
  `numpy.random.Generator`, so every run and test is reproducible.

## License

[MIT](LICENSE)
