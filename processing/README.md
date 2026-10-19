# processing

Streaming vibration processing: keeps a bounded rolling window of the sensor's
acceleration, computes features for each window, and flags anomalies. This
version works on any iterable of sample chunks. Reading from MQTT and writing to the
spool come in later features.

## Installation

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
cd processing
uv sync
```

## Usage

`process()` takes chunks of samples and yields one `WindowResult(end_sample,
features, is_anomaly)` every 250 samples once the window is full:

```python
import numpy as np

from processing.config import ProcessingConfig
from processing.processor import process

recording = np.load("../docs/contract/fixtures/seed_0.npz")
acceleration = recording["acceleration"].astype(float)
chunks = (acceleration[i : i + 50] for i in range(0, len(acceleration), 50))
for result in process(chunks, ProcessingConfig.from_env()):
    if result.is_anomaly:
        print(result.end_sample / 1000, result.features)
```

## Configuration

`ProcessingConfig.from_env()` reads these environment variables into a frozen
dataclass:

| Variable | Default | Meaning |
|---|---|---|
| `PROCESSING_SAMPLE_RATE_HZ` | 1000 | sample rate of the incoming stream (Hz) |
| `PROCESSING_WINDOW_SIZE` | 1024 | window length in samples (1.024 s) |
| `PROCESSING_HOP_SIZE` | 250 | samples between two windows (4 windows/s) |
| `PROCESSING_WARMUP_S` | 10 | stream time used to learn the baseline (s) |
| `PROCESSING_Z_THRESHOLD` | 4 | \|z\| above which a feature is an outlier |
| `PROCESSING_CONSECUTIVE_WINDOWS` | 2 | outlier windows in a row needed for an anomaly |

## Design

**Window.** `RingBuffer` is one preallocated numpy array of 1024 floats plus a write
index. Each append overwrites the oldest value. Memory is fixed when the buffer is
created and never grows with run length. 1024 samples is 1.024 s at 1 kHz, which is
inside the required 1-2 s and a power of two for the FFT.

**Hop.** A new window is evaluated every 250 samples. That gives four results per
second (detection latency of a few hundred ms), while the FFT work stays small.

**Features** (`compute_features`) for each window:
- RMS, mean and standard deviation.
- Dominant frequency: subtract the mean, apply a Hann taper, take `rfft`, skip the DC
  bin, then fit a parabola through the peak bin and its two neighbours in log power.
  Bins are 0.98 Hz apart, and the interpolation finds a clean sine to within 0.1 Hz.
  The mean is removed first because the Hann taper would otherwise spread a DC offset
  (gravity, sensor bias) into the lowest bins, where it can beat the real peak. A test
  caught this.

**Detector.** The first 10 s (40 windows) build a baseline mean and std for each
feature, updated one window at a time with Welford's method. The baseline then
freezes, so a slowly developing fault can't become the new normal. After warm-up, a
window is an outlier if any feature has \|z\| > 4. An anomaly is reported only after
2 outlier windows in a row, which suppresses single noisy windows at the cost of one
hop (250 ms) of latency.

**No look-ahead.** `process()` is a generator. It yields a result as soon as the
window's newest sample arrives, so a result can only depend on past samples. A test
changes every sample after t = 12 s and checks that no earlier result changes.

## Evaluation

`evaluate()` compares the flags with the known fault, given as sample indices from the
sensor's `get_fault_ranges`. A window is **faulty** when at least half of it lies
inside the fault. It's a true positive if flagged and faulty, a false positive if
flagged and not faulty, and a false negative if faulty and not flagged. **Latency** is
the time from fault start to the first flagged window that ends inside the fault.

The test data are the committed sensor recordings in `docs/contract/fixtures/` (seeds
0-4, 40 s each, fault at 20-30 s, default parameters). Processing never imports the
sensor package, so these files are the only link between the two.

**Results on the fixtures** (default fault: natural frequency ×1.3, damping ×0.5):

| seed | TP | FP | FN | precision | recall | latency |
|---|---|---|---|---|---|---|
| 0 | 40 | 2 | 0 | 0.95 | 1.00 | 0.50 s |
| 1 | 40 | 0 | 0 | 1.00 | 1.00 | 0.75 s |
| 2 | 40 | 0 | 0 | 1.00 | 1.00 | 0.75 s |
| 3 | 40 | 0 | 0 | 1.00 | 1.00 | 0.75 s |
| 4 | 40 | 0 | 0 | 1.00 | 1.00 | 0.75 s |

There are no false alarms during the 10 s of normal operation after warm-up. The only
two false positives (seed 0) are at the trailing edge: windows just after the fault
still hold up to half a window of fault data.

**Weak spots.** The default fault moves the resonance by 15 Hz, which is easy. I also
ran the same detector on weaker faults (5 seeds each, generated ad hoc, not committed):

| fault | precision | recall | detected |
|---|---|---|---|
| frequency ×1.3, damping ×0.5 (default) | 0.99 | 1.00 | 5/5 |
| frequency ×1.1 (50 → 55 Hz) | 0.40 | 0.04 | 2/5 |
| frequency ×1.05 or ×1.02 | 0.00 | 0.00 | 0/5 |
| damping ×0.5 only | 1.00 | 0.39 | 5/5, latency up to 8.5 s |
| damping ×2 only | 0.40 | 0.01 | 2/5 |

The cause is the noisy frequency estimate. In normal operation the peak of a single
1 s window wanders by about ±2 Hz (std across windows, seeds 0-4). A noise-driven
resonance with ζ = 0.05 has a half-power bandwidth of 2ζfₙ = 5 Hz, and one short FFT
of it is a noisy estimate. With \|z\| > 4, a shift needs to be about 8 Hz before it
stands out. Damping changes mostly change the RMS level, which is also noisy per
window (±0.1 on 1.6).

With more time, I'd improve this by smoothing before thresholding, not by tuning the
threshold:
- an EWMA or CUSUM on the peak frequency, which accumulates small persistent shifts
- Welch-averaged spectra over several windows
- spectral band energy around the baseline resonance instead of the single peak bin

Each of these trades latency for sensitivity.

## Throughput and memory

`scripts/benchmark.py` feeds 10 minutes of stream time (the five fixtures, looped) into
`process()` in chunks of 50 samples, as fast as possible:

```sh
uv run python scripts/benchmark.py
```

Measured on one core (`taskset -c 0`) of an Intel Xeon Platinum 8259CL @ 2.5 GHz (an
AWS VM):

```
stream time:      600 s (600000 samples)
wall time:        0.98 s
throughput:       612273 samples/s (612x real time)
tracemalloc peak: 83.8 KiB
RSS start / end:  36.2 / 37.8 MiB
```

- **Throughput:** about 600k samples/s, roughly 600 times the required 1000 samples/s.
  Most of the time goes to the per-sample Python loop, not the FFT.
- **Memory of the loop:** the tracemalloc peak covers only Python allocations made
  while `process()` runs, with the input loaded beforehand. It's about 84 KiB: the
  1024-float ring (8 KiB), a few window-sized temporaries for the FFT, and the
  detector's baseline. A one-hour run gives the same peak and the same RSS, so memory
  doesn't grow with run length.
- **Process RSS:** about 38 MiB, almost all of it the Python interpreter and numpy. The
  1.6 MiB rise between start and end happens once (numpy's FFT setup and allocator),
  not per window.

**Verifying on constrained hardware.** Run the same script on the device. The
tracemalloc peak depends only on the window size, so it should match. RSS and
throughput depend on the CPU and the Python/numpy build. Pin it to one core with
`taskset -c 0`, and read the process's peak RSS from `VmHWM` in `/proc/<pid>/status`.
A throughput of at least 1000 samples/s, with headroom for the MQTT and spool work
added later, is the bar.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The tests cover:
- the ring buffer: memory stays bounded after a million appends (tracemalloc), plus
  oldest-first snapshots that are copies
- features on pure sines: RMS, mean, std, and a peak found between bins to within
  0.1 Hz, including with a DC offset
- the detector: one outlier window isn't an anomaly, two in a row are, and the
  Welford stats match the textbook values
- the detector against the known fault window on all five recordings: the fault is
  detected on every seed, latency < 1.5 s, and mean precision and recall ≥ 0.8
- the processor: a result every hop, no look-ahead, and the same results however the
  stream is chunked
- reading the configuration from the environment
