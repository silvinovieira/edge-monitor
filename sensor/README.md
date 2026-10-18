# sensor

Simulated vibration sensor: an accelerometer on a machine modelled as a noise-driven
damped harmonic oscillator, with injectable faults that give a known ground-truth
window.

## Usage

`simulate()` is a generator that yields one `Sample(t, accel, in_fault)` at a time,
forever. The caller decides how much to take:

```python
from itertools import islice

from sensor.config import SensorConfig
from sensor.simulator import simulate

cfg = SensorConfig.from_env()
for sample in islice(simulate(cfg, [cfg.default_fault()]), 5):
    print(sample)
```

```sh
cd sensor
uv sync
SENSOR_SEED=3 uv run python your_script.py
```

The simulator does no pacing: it runs as fast as the CPU allows (about 260k–300k
samples/s in pure Python on one laptop core), far above the 1 kHz real-time rate.

## Configuration

Read from environment variables by `SensorConfig.from_env()` into a frozen dataclass.

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

`SensorConfig` rejects any `fs` where ωₙ·dt > 1 (including the faulted ωₙ), to keep
RK4 well inside its stability limit and accurate.

## Model

    x''(t) + 2·ζ·ωₙ·x'(t) + ωₙ²·x(t) = F(t),    ωₙ = 2π·fₙ,   F ~ N(0, σ²)

The state `[x, v]` is integrated with classic RK4 at `dt = 1/fs`. Each sample is the
acceleration an accelerometer would measure:

    a = F − 2·ζ·ωₙ·v − ωₙ²·x

**Fault injection.** A `Fault(start, duration, omega_scale, zeta_scale)` covers the
half-open window `[start, start + duration)`. Inside it, ωₙ and ζ are scaled. Outside
it, they return to baseline. The default fault moves the resonance from 50 Hz to 65 Hz
and halves the damping, which models a stiffness change (for example a loosened or
cracked mount) with less energy dissipation. `in_fault` is the ground truth for each
sample.

**Measured behaviour** (default parameters, seeds 0–4, averaged 1 s Hann periodograms):

| | dominant frequency | accel std |
|---|---|---|
| baseline (2–20 s) | 49–51 Hz | 1.57–1.67 |
| fault (21–30 s) | 64–65 Hz | 2.16–2.35 |

**Assumptions and choices**
- `F` is drawn once per step and held constant across the four RK4 stages, so the noise
  acts as a zero-order-hold input. Drawing it separately for each stage would change its
  effective variance.
- Time comes from the sample index (`t = n / fs`), not from summing `dt`, so fault
  boundaries land on exact samples (20 000 and 30 000 at 1 kHz).
- Sample `n` is `x''` at `t_n`. It uses the state at `t_n` and that step's force, and
  then the state advances. The oscillator starts at rest. The decay time 1/(ζωₙ) is
  ≈ 64 ms, so the start-up transient is gone within a few hundred ms.
- When the parameters change at a fault boundary, the state carries over continuously.
  The physical system changes, but it doesn't jump.

## Fixtures

`scripts/make_fixtures.py` writes `docs/contract/fixtures/seed_{0..4}.npz`: 40 s per
seed, with the default fault at 20–30 s. Each file holds `accel` (float32, 40 000
samples), `fault_windows` (`[[start, end)]`, float64), `fs` and `seed`. It always uses
the default parameters and ignores `SENSOR_*` variables, because other services' tests
depend on these files.

```sh
uv run python scripts/make_fixtures.py
```

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The tests cover determinism (same seed gives identical output), the FFT peak (≈ 50 Hz
at baseline, ≈ 65 Hz in the fault), and `in_fault` being true exactly in `[20, 30)`.
