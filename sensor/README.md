# sensor

Simulated vibration sensor: an accelerometer on a machine modelled as a noise-driven
damped harmonic oscillator, with injectable faults that give a known ground-truth
window.

## Usage

### Command line

`python -m sensor` simulates a stretch of stream time and writes the samples as CSV to
stdout. Log messages go to stderr, so redirecting stdout gives a clean data file.

```sh
cd sensor
uv sync
uv run python -m sensor --seconds 2 > samples.csv
SENSOR_SEED=3 SENSOR_FAULT_START=0.5 uv run python -m sensor --seconds 1 | head
uv run python -m sensor --no-fault --seconds 5
```

```
t,accel,in_fault
0.000,0.125730,0
0.001,-0.142018,0
...
```

`--seconds` is stream time, not wall time: there is no pacing, so it runs as fast as
the CPU allows.

### From Python

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

The simulator does no pacing: it runs as fast as the CPU allows (about 230k samples/s
in pure Python on one laptop core), far above the 1 kHz real-time rate.

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
cracked mount) with less energy dissipation. `in_fault` is the ground truth for each
sample.

**Measured behaviour** (default parameters, seeds 0–4, averaged 1 s Hann periodograms):

| | dominant frequency | accel std |
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
- `in_fault` being true exactly in `[20, 30)`
- exact fault windows even when `start + duration` isn't exact in floating point
- rejection of invalid, overlapping, too-short or too-fast faults
- the command line: CSV format, sample count, fault flag, `--no-fault`
- reading the configuration from the environment
