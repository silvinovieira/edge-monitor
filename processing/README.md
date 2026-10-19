# processing

Streaming vibration processing: keeps a bounded rolling window of the sensor's
acceleration, computes features for each window, flags anomalies, and writes
compressed 60 s batches to an on-disk spool for the sync service. It reads the
sensor's stream from MQTT. The core also works on any iterable of sample chunks, which
is how the tests and the benchmark use it.

## Installation

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
cd processing
uv sync
```

## Usage

Run the service: subscribe to the sensor on `localhost:1883` (or
`PROCESSING_MQTT_HOST`) and write batches to `./spool` (or `PROCESSING_SPOOL_DIR`)
until Ctrl-C or SIGTERM. With evaluation on, it also logs precision and recall against
the ground truth at shutdown:

```sh
PROCESSING_EVALUATE=true uv run python -m processing
```

On shutdown it writes the last, shorter batch, so nothing processed is lost.

As a library:

`process()` takes chunks of samples and yields one `WindowResult(start_sample,
end_sample, features, is_anomaly)` every 250 samples once the window is full. The
window covers samples `[start_sample, end_sample)`:

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

`make_batches()` runs the same processing and groups its output into one `Batch` per
60 s of stream time. `SpoolWriter` writes each batch atomically into the spool:

```python
from processing.batcher import make_batches
from processing.spool_writer import SpoolWriter

cfg = ProcessingConfig.from_env()
chunks = (acceleration[i : i + 50] for i in range(0, len(acceleration), 50))
writer = SpoolWriter(cfg.spool_dir)
for batch in make_batches(chunks, cfg, stream_start_ns=1_767_225_600_000_000_000):
    print(writer.write(batch))  # spool/ready/1767225600000000000_sensor-1.jsonl.gz
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
| `PROCESSING_SENSOR_ID` | sensor-1 | sensor name in batches and file names (letters, digits, `-`) |
| `PROCESSING_SPOOL_DIR` | spool | spool directory, shared with the sync service |
| `PROCESSING_BATCH_S` | 60 | stream time per batch (s) |
| `PROCESSING_SUMMARY_RATE_HZ` | 10 | rate of the downsampled samples in each batch (Hz) |
| `PROCESSING_MQTT_HOST` | localhost | MQTT broker host |
| `PROCESSING_MQTT_PORT` | 1883 | MQTT broker port |
| `PROCESSING_QUEUE_SIZE` | 1000 | chunks buffered between MQTT and the loop (50 s) |
| `PROCESSING_EVALUATE` | false | subscribe to the ground truth and log precision/recall at shutdown |

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

## MQTT input and backpressure

paho receives messages on its own network thread and puts them in a bounded
`queue.Queue` (1000 chunks, 50 s of data). The processing loop takes them out one at a
time.

- **When the queue is full, the oldest chunk is dropped and counted.** The queue
  never grows past its limit, so a stalled loop can't exhaust memory. Dropping the
  oldest data, not the newest, keeps the detector looking at the present, which is
  what matters for a live alarm. In practice the loop is about 440 times faster than
  real time, so the queue should stay almost empty. The drop count is logged at
  shutdown, along with every drop as it happens.
- **Invalid messages are dropped and counted.** A samples message must be JSON with
  an integer `seq` and `t0_ns`, a positive `dt_s` and a non-empty list of numbers. Any
  other message on the topic is logged, counted (`invalid messages` at shutdown) and
  dropped. This matters because an exception in paho's callback kills its network
  thread: before this check, one malformed message from any client silently stopped
  all input.
- **Chunks still queued at shutdown are lost.** paho acknowledges a message to the
  broker as soon as it reaches the queue, so on SIGTERM the few chunks still in the
  queue (normally almost none, since the loop is far faster than the stream) are
  never processed, and the broker won't resend them. Acknowledging only after a chunk
  has been processed (paho's manual acks) would close that gap.
- **Gaps in `seq` are logged and counted.** Processing then carries on as if the
  stream were contiguous. Timestamps come from the sample index, so after a gap, later
  timestamps are early by the missing time. Inserting the missing samples (or
  restarting the time base) would fix that. It's listed as missing in the root README.
- **Restarts don't lose data at the broker.** Processing connects with a fixed client
  id and a persistent session (`clean_session=False`), so while it is down, mosquitto
  keeps queueing its QoS 1 messages and delivers them when it reconnects. Mosquitto's
  default limit is 1000 queued messages per client, about 50 s.
- **Time comes from the stream.** The first message's `t0_ns`, minus its `seq` offset,
  gives the wall-clock time of sample 0. Every batch timestamp follows from the sample
  index, so batch boundaries are exact.
- **Ground truth only for the evaluator.** Processing subscribes to
  `sensors/<id>/truth` only when `PROCESSING_EVALUATE` is on, and the truth goes only
  to the `Evaluator`, never to the detector. The evaluator keeps running counts, not a
  list of results, so live evaluation doesn't grow memory either.

## Batches and spool

The full format is in [`docs/spool-contract.md`](../docs/spool-contract.md), with a
real example in `docs/contract/example_batch.jsonl.gz`.

**What a batch holds.** One batch covers 60 s of stream time. It has a header line,
one line per window (features and anomaly flag), and one line with the stream
downsampled to 10 Hz (mean and RMS of every 100 samples). A window belongs to the
batch in which it ends. Chunks are split at batch boundaries, so every sample lands in
exactly one batch however the stream is chunked. When the stream ends, the samples
since the last full batch go out as a shorter final batch. Times are computed from the
sample index and `stream_start_ns`, the wall-clock time of the first sample.

**Why gzip JSONL.** It needs no dependency beyond the standard library, any tool can
read it (`zcat file | jq`), and an extra field doesn't break old readers.
Parquet would be smaller and faster to query, but it needs pyarrow on the edge device
(a large binary dependency) and buffering to build row groups. At about
23 KB per minute, size isn't the bottleneck. If it ever is, Parquet can be produced in
the cloud from these files.

**Why 60 s batches and not one file per window.** A window line is about 200 bytes. As
separate files, that would be 4 files and 4 S3 PUTs per second, each with more
overhead than data. Over a slow link, one 23 KB upload per minute costs far less.
Batching also compresses much better: gzip shrinks a whole batch 3.1x (72 KB → 23 KB),
but a single window only 1.3x (202 → 160 bytes). The cost is that a crash can lose up to one
minute of output that hasn't been written yet, and the cloud sees data up to a minute
late. Alerts that need to be faster would go over a separate, small channel.

**Durability.** `SpoolWriter.write()` follows the same steps every time:
1. Write the gzip bytes into `tmp/<name>`.
2. Flush and `fsync` the file, so the data is on disk.
3. `os.replace` it into `ready/<name>`. The rename is atomic, so the sync service sees
   the whole file or nothing.
4. `fsync` the `ready/` directory, so the rename itself survives a power cut.

A crash can therefore leave only an unfinished file in `tmp/`, which the writer
deletes on its next start.

**Deterministic file names.** A file is named `{start_ns}_{sensor_id}.jsonl.gz`, and
gzip is written with `mtime=0`. The same batch always gives the same name and the same
bytes. A batch rewritten after a crash replaces itself instead of becoming a
duplicate, and the sync service can derive a stable S3 key from the name. The
19-digit zero-padded timestamp comes first, so sorting by name is sorting by time.
There is no random part, because the project only allows seeded randomness.

**Disk sizing.** Measured with the example batch: a full 60 s batch is 23.3 KB
gzipped (72 KB uncompressed), so about 390 B/s, 1.4 MB/h, or 34 MB/day per sensor. The
spool must hold everything produced during the longest outage to survive:

```
disk = bytes/s × outage × safety factor
     = 390 B/s × 7 days × 2 ≈ 470 MB per sensor
```

There is no size cap yet. If the disk fills up, writes fail and the error is visible
in the logs. A cap that evicts the oldest batches and counts the drops is planned for
when time allows (see `docs/PLAN.md`). Rounding the floats to 6 significant digits,
far more than the sensor's real precision, would cut a batch from 23 KB to 11 KB
(measured on the example batch).

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

`scripts/benchmark.py` feeds 10 minutes of stream time (the five fixtures, looped)
through the whole loop as fast as possible, in chunks of 50 samples: processing,
batching and gzip encoding. Disk writes are left out, because their cost depends on
the storage, not on this code:

```sh
uv run python scripts/benchmark.py
```

Measured on one core (`taskset -c 0`) of an Intel Xeon Platinum 8259CL @ 2.5 GHz (an
AWS VM):

```
stream time:      600 s (600000 samples)
wall time:        1.36 s
throughput:       440903 samples/s (441x real time)
tracemalloc peak: 740.4 KiB
RSS start / end:  36.6 / 39.2 MiB
```

- **Throughput:** about 440k samples/s, roughly 440 times the required 1000 samples/s.
  Most of the time goes to the per-sample Python loops (window and downsampler), not
  the FFT or gzip.
- **Memory of the loop:** the tracemalloc peak covers only Python allocations made
  while the loop runs, with the input loaded beforehand. It's under 1 MiB, and almost
  all of it is one batch being built and encoded: 240 window records, 600 points and
  their JSON text. The window itself (the 1024-float ring, 8 KiB) and the detector's
  baseline are small. Measured over increasing run lengths, the peak levels off:

  | stream time | 2 min | 5 min | 10 min | 30 min | 1 h | 2 h |
  |---|---|---|---|---|---|---|
  | tracemalloc peak | 921 KiB | 891 KiB | 985 KiB | 986 KiB | 985 KiB | 985 KiB |

  The peak varies a little between runs with garbage collection timing (740 KiB above,
  985 KiB here), but it doesn't grow with run length.
- **Process RSS:** about 39 MiB, almost all of it the Python interpreter and numpy. The
  2.6 MiB rise between start and end happens once (numpy's FFT setup and allocator),
  not per window.

**The running container.** Measured in the compose run, after several minutes of the
live 1 kHz stream from MQTT:

| | value |
|---|---|
| CPU | 1.3-1.5% of one core |
| memory (cgroup, `docker stats`) | 25.6 MiB, then 25.8 MiB five minutes later |
| peak RSS (`VmHWM`) | 43.5 MiB, then 43.6 MiB five minutes later |

Under a hard limit of `--memory 64m --cpus 0.25`, the same image ran against the live
sensor at 25.8 MiB with no dropped chunks and no OOM kill, and it detected the fault
(precision 0.95, recall 1.00).

**Verifying on constrained hardware.** Run the same script on the device. The
tracemalloc peak depends only on the window and batch sizes, so it should match. RSS and
throughput depend on the CPU and the Python/numpy build. Pin it to one core with
`taskset -c 0`, and read the process's peak RSS from `VmHWM` in `/proc/<pid>/status`.
For the running service, start it with a cgroup limit below the device's budget and
watch for drops and OOM kills:

```sh
docker run --memory 64m --memory-swap 64m --cpus 0.25 \
  -e PROCESSING_MQTT_HOST=<broker> edge-monitor-processing
docker exec <container> grep VmHWM /proc/1/status   # peak RSS
docker inspect -f '{{.State.OOMKilled}}' <container>
```

The log line `dropped chunks: N` at shutdown shows whether it kept up. On a bare
device without Docker, `systemd-run -p MemoryMax=64M -p CPUQuota=25% …` applies the
same limits.
A throughput of at least 1000 samples/s, with headroom for the MQTT input and the disk
writes, is the bar.

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
- the downsampler: mean and RMS per block, blocks spanning chunks
- the batcher: one batch per minute with a shorter last batch, 240 windows and 600
  points per batch, file names, and the same batches whatever the chunk size
- the spool writer: complete files in `ready/`; a crash before the rename leaves
  nothing in `ready/`; a restart removes unfinished files in `tmp/` and keeps finished
  ones
- the contract: the committed example batch has the documented lines and fields, and
  is byte-for-byte what the current code writes
- the subscriber, with fake MQTT messages: arrival order, dropping the oldest chunk
  when the queue is full, counting `seq` gaps, keeping the truth out of the sample
  queue, ignoring other sensors, and dropping invalid messages (bad JSON, missing or
  wrongly typed fields) without blocking the valid ones after them
- the incremental `Evaluator` giving the same result as `evaluate()`
- reading the configuration from the environment
