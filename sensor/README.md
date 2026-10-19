# sensor

Simulated vibration sensor: an accelerometer on a machine modelled as a noise-driven
damped harmonic oscillator, with injectable faults that give a known ground-truth
window.

## Installation

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/). `uv sync` creates `.venv`
and installs the package with the dependencies from `pyproject.toml`, pinned by
`uv.lock` (including the dev group: pytest, ruff):

```sh
cd sensor
uv sync
```

Without uv, an editable pip install from `pyproject.toml` works too (no dev tools):

```sh
cd sensor
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e .
```

## Usage

Print one second of samples with the configuration from the environment:

```sh
uv run python -m sensor.simulator
SENSOR_SEED=3 SENSOR_FAULT_START=0.5 uv run python -m sensor.simulator
```

In your own code, `simulate()` is a generator that yields one
`Sample(time_s, acceleration)` at a time, forever. The caller decides how much to
take:

```python
from itertools import islice

from sensor.config import SensorConfig
from sensor.simulator import simulate

cfg = SensorConfig.from_env()
for sample in islice(simulate(cfg, [cfg.default_fault()]), 5):
    print(sample)
```

The simulator does no pacing: it runs as fast as the CPU allows (about 37k samples/s
on one core), far above the 1 kHz real-time rate.

## Configuration

`SensorConfig.from_env()` reads these environment variables into a frozen dataclass:

| Variable | Default | Meaning |
|---|---|---|
| `SENSOR_SAMPLE_RATE_HZ` | 1000 | sample rate (Hz) |
| `SENSOR_NATURAL_FREQ_HZ` | 50 | natural frequency fₙ (Hz) |
| `SENSOR_DAMPING_RATIO` | 0.05 | damping ratio ζ |
| `SENSOR_NOISE_STD` | 1.0 | σ of the forcing, per sample |
| `SENSOR_SEED` | 0 | seed of the `numpy.random.Generator` |
| `SENSOR_FAULT_START` | 20 | fault start (s) |
| `SENSOR_FAULT_DURATION` | 10 | fault duration (s) |
| `SENSOR_FAULT_FREQ_SCALE` | 1.3 | natural frequency multiplier during the fault |
| `SENSOR_FAULT_DAMPING_SCALE` | 0.5 | damping ratio multiplier during the fault |

`simulate()` checks its input when called, before the first sample:
- Fault boundaries are converted to sample indices (rounded to the nearest sample).
  Membership is then an integer comparison, so float sums like 0.2 + 0.1 can't move a
  boundary.
- It rejects overlapping faults, and faults shorter than one sample.
- It rejects any configuration where ωₙ·dt > 1, including the faulted ωₙ, to stay well
  inside RK4's stability limit. With the defaults, ωₙ·dt is 0.41 during the fault.
- `Fault` itself rejects a negative start, a non-positive duration, and scales that are
  out of range.

## Model

    x''(t) + 2·ζ·ωₙ·x'(t) + ωₙ²·x(t) = F(t),    ωₙ = 2π·fₙ,   F ~ N(0, σ²)

x is displacement, ωₙ the angular natural frequency, ζ the damping ratio and F the
forcing. The state `[displacement, velocity]` is integrated with classic RK4 at
`dt = 1/sample_rate_hz`. Each sample is the acceleration an accelerometer would measure:

    a = F − 2·ζ·ωₙ·v − ωₙ²·x

So each sample contains the white forcing term itself on top of the resonant response.

**Fault injection.** A `Fault(start, duration, freq_scale, damping_scale)` covers the
half-open window `[start, start + duration)`. Inside it, ωₙ and ζ are scaled. Outside
it, they return to baseline. The default fault moves the resonance from 50 Hz to 65 Hz
and halves the damping, which models a stiffness change (for example a loosened or
cracked mount) with less energy dissipation. Samples carry no fault label: the ground
truth comes from `get_fault_ranges(cfg, faults)`, which returns the sample indices each
fault covers. The simulator applies faults from the same ranges, so the two can't
disagree.

**Measured behaviour** (default parameters, seeds 0–4, averaged 1 s Hann periodograms):

| | dominant frequency | acceleration std |
|---|---|---|
| baseline (2–20 s) | 49–51 Hz | 1.57–1.67 |
| fault (21–30 s) | 64–65 Hz | 2.16–2.35 |

**Assumptions and choices**
- The forcing is drawn once per step and held constant across the four RK4 stages, so
  it acts as a zero-order-hold input. Drawing it separately for each stage would change
  its effective variance.
- `noise_std` is per sample and isn't rescaled with the step length. Changing the
  sample rate therefore changes the response level. That's acceptable because the rate
  is fixed for the whole run. A continuous noise intensity scaled by 1/√dt would remove
  that coupling.
- Time comes from the sample index (`t = sample_index / sample_rate_hz`), not from
  summing `dt`, so fault boundaries land on exact samples (20 000 and 30 000 at 1 kHz).
- Sample n is `x''` at `t_n`. It uses the state at `t_n` and that step's forcing, and
  then the state advances. The oscillator starts at rest. The decay time 1/(ζωₙ) is
  ≈ 64 ms, so the start-up transient is gone within a few hundred ms.
- When the parameters change at a fault boundary, the state carries over continuously.
  The physical system changes, but it doesn't jump.

## Fixtures

`scripts/make_fixtures.py` records 40 s of the default configuration for seeds 0-4
into `docs/contract/fixtures/seed_<seed>.npz`. Processing tests and benchmarks run
against these files without importing this package. Each file holds `acceleration`
(float32), `sample_rate_hz`, and the fault as sample indices `fault_start` and
`fault_stop` (from `get_fault_ranges`). The script ignores environment variables, so
it always regenerates the same bytes:

```sh
uv run python scripts/make_fixtures.py
```

Rerun it, and commit the result, whenever the simulator's output changes.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The tests cover:
- determinism: the same seed gives identical output, and a different seed gives
  different output
- the FFT peak: ≈ 50 Hz at baseline and ≈ 65 Hz in the fault
- the default fault covering exactly samples `[20 000, 30 000)`
- exact fault ranges even when `start + duration` isn't exact in floating point
- rejection of invalid, overlapping, too-short or too-fast faults
- reading the configuration from the environment
