# edge-monitor

Edge vibration monitoring in Python: simulated sensor with fault injection, bounded-memory
streaming anomaly detection, and a crash-safe disk queue syncing batches to S3
(LocalStack/moto).

## Overview

The system is planned as three independent services. **sensor** simulates an
accelerometer on a vibrating machine and streams samples with known fault windows.
**processing** consumes that stream in real time with a bounded rolling window,
computes features, flags anomalies, and writes compressed batches to an on-disk spool.
**sync** uploads spooled batches to S3, retrying with backoff when connectivity drops.
Processing and sync share only the spool directory. Right now only the sensor's
simulator exists. The other services and the MQTT transport are added feature by
feature (see `docs/PLAN.md`).

## Repository layout

```
sensor/                    uv project: vibration sensor simulator
  sensor/config.py         SensorConfig (frozen dataclass, read from env vars)
  sensor/simulator.py      RK4 oscillator, fault windows, sample generator
  scripts/make_fixtures.py writes the shared test fixtures
  tests/                   pytest suite
docs/
  PLAN.md                  feature order
  contract/fixtures/       seed_{0..4}.npz, 40 s of simulated data per seed
.github/workflows/ci.yml   ruff + pytest for each service
```

## Running the tests

Requires [uv](https://docs.astral.sh/uv/). From the service directory:

```sh
cd sensor
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Regenerate the fixtures (deterministic; always uses the default parameters):

```sh
cd sensor
uv run python scripts/make_fixtures.py
```

## Sensor model

The sensor is a single-degree-of-freedom damped harmonic oscillator driven by noise:

    x''(t) + 2·ζ·ωₙ·x'(t) + ωₙ²·x(t) = F(t),    ωₙ = 2π·fₙ,   F ~ N(0, σ²)

The simulator integrates the state `[x, v]` with classic RK4 at `dt = 1/fs`. It emits
the acceleration an accelerometer would measure:

    a = F − 2·ζ·ωₙ·v − ωₙ²·x

`simulate(cfg, faults)` is an endless generator that yields one
`Sample(t, accel, in_fault)` at a time. It does no pacing; real-time pacing will be
a separate layer.

**Parameters** (environment variables, read by `SensorConfig.from_env()`):

| Variable | Default | Meaning |
|---|---|---|
| `SENSOR_FS` | 1000 | sample rate (Hz) |
| `SENSOR_F_N_HZ` | 50 | natural frequency fₙ (Hz) |
| `SENSOR_ZETA` | 0.05 | damping ratio ζ |
| `SENSOR_NOISE_STD` | 1.0 | σ of the forcing noise |
| `SENSOR_SEED` | 0 | seed of the `numpy.random.Generator` |
| `SENSOR_FAULT_START` | 20 | fault start (s) |
| `SENSOR_FAULT_DURATION` | 10 | fault duration (s) |
| `SENSOR_FAULT_OMEGA_SCALE` | 1.3 | ωₙ multiplier during the fault |
| `SENSOR_FAULT_ZETA_SCALE` | 0.5 | ζ multiplier during the fault |

**Fault injection.** A `Fault(start, duration, omega_scale, zeta_scale)` covers the
half-open window `[start, start + duration)`. Inside it, ωₙ and ζ are scaled. Outside
it, they return to baseline. The default fault moves the resonance from 50 Hz to 65 Hz
and halves the damping, which models a stiffness change (for example a loosened or
cracked mount) with less energy dissipation. `in_fault` gives the ground truth for each
sample.

**Measured behaviour** (default parameters, seeds 0–4, averaged 1 s Hann periodograms):

| | dominant frequency | accel std |
|---|---|---|
| baseline (2–20 s) | 49–51 Hz | 1.57–1.67 |
| fault (21–30 s) | 64–65 Hz | 2.16–2.35 |

The generator produces about 260k–300k samples/s in pure Python on one core, far above
the 1 kHz real-time rate.

**Assumptions and choices**
- `F` is drawn once per step and held constant across the four RK4 stages, so the noise
  acts as a zero-order-hold input. Drawing it separately for each stage would change its
  effective variance.
- Time comes from the sample index (`t = n / fs`), not from summing `dt`, so fault
  boundaries land on exact samples (20 000 and 30 000 at 1 kHz).
- Sample `n` is `x''` at `t_n`. It uses the state at `t_n` and that step's force, and
  then the state advances. The oscillator starts at rest. The decay time 1/(ζωₙ) is
  ≈ 64 ms, so the start-up transient is gone within a few hundred ms. The tests skip
  the first 2 s to leave a margin.
- When the parameters change at a fault boundary, the state carries over continuously.
  The physical system changes, but it doesn't jump.
- `SensorConfig` rejects an `fs` where ωₙ·dt > 1 (including the faulted ωₙ), to keep
  RK4 well inside its stability limit and accurate.
- Fixtures (`docs/contract/fixtures/seed_N.npz`) contain `accel` (float32, 40 000
  samples), `fault_windows` (`[[start, end)]`, float64), `fs` and `seed`. They are the
  shared input for the processing tests.
