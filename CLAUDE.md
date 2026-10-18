# CLAUDE.md

## Project

Edge vibration monitoring, built as three independent services:

- **sensor/**: simulates a vibration sensor (damped harmonic oscillator, RK4, injectable
  faults) and publishes samples over MQTT in chunks of 50.
- **processing/**: subscribes to the samples, keeps a bounded rolling window, computes
  features (RMS, mean, std, FFT peak), detects anomalies, and writes compressed 60 s
  batches (features, flags, 10 Hz samples) to an on-disk spool.
- **sync/**: reads batches from the spool and uploads them to S3 (LocalStack), retrying
  with backoff during outages.

`processing` and `sync` run on the same edge device but are separate processes. They
share only the spool directory, whose format is defined in `docs/spool-contract.md`.

The feature order is in `docs/PLAN.md`. Work on one feature at a time.

## Requirements (the source of truth; check every feature against them)

**Sensor (Part 1)**
- Synthetic vibration from a damped harmonic oscillator driven by noise:

      x''(t) + 2·ζ·ωₙ·x'(t) + ωₙ²·x(t) = F(t)

  where x is displacement, ωₙ the natural frequency (rad/s, = 2π·fₙ), ζ the damping
  ratio, and F(t) mostly Gaussian noise (normal operating vibration).
  Integrate it numerically with RK4 on the state [x, v] at a configurable rate
  (default 1 kHz). Emit acceleration a = F − 2·ζ·ωₙ·v − ωₙ²·x (what an accelerometer
  measures).
- Fault injection: at a chosen time, change the natural frequency and/or damping for a
  configurable duration, then return to baseline. This gives a known ground-truth window.
- Samples are emitted as a stream, never as a precomputed array.

**Processing (Part 2)**
- Consumes the stream in (simulated) real time.
- Bounded rolling window of 1-2 s in an efficient structure; memory must never grow with
  run length.
- Per window: RMS, rolling mean and std, dominant frequency (FFT peak). No look-ahead.
- Flags anomalies and reports precision/recall-style metrics against the known fault
  window.
- Sustains at least 1000 samples/s on one laptop core without falling behind, with a
  benchmark that demonstrates it.

**Cloud sync (Part 3)**
- Batches processed output (features, anomaly flags and 10 Hz samples), compresses it,
  and uploads it to S3 mocked locally (LocalStack; no real AWS).
- Uploads must sometimes fail (simulated intermittent connectivity). Unsent batches are
  buffered durably on disk so nothing is lost across a process restart, and retried with
  backoff when connectivity returns.
- The S3 object layout is designed deliberately and justified in the README.

**Constraints**
- Python; any non-obvious library must be justified in the README.
- The processing loop has a bounded, predictable memory footprint; the README states the
  figure and how to verify it on constrained hardware.
- Processing and sync are decoupled: processing never blocks on S3.

**Required tests (at minimum)**
- The anomaly detector against the known fault window.
- The rolling window's bounded memory.
- The durable queue surviving a restart.

**README must cover**
- How to run everything end to end (sensor → processing → sync).
- Key design decisions, trade-offs, and what would change with more time.
- What is missing, if anything, and how it would be approached.
- A few paragraphs on taking this to production on real edge hardware with AWS: runtime
  and orchestration (e.g. Greengrass vs systemd), OTA updates, observability and alerting
  over constrained connectivity, and sizing throughput and memory for real hardware.

**Out of scope:** production IAM/networking, any UI (logs or CLI output are enough),
tuned detection accuracy (an honest evaluation matters more), exhaustive test coverage.

**Optional, only if time remains:** EWMA or Kalman detector compared with the baseline
one; 2-3 sensors with correlated anomalies; a one-page design for large-scale AWS
ingestion.

## Workflow (follow strictly, for every feature)

1. Start from an up-to-date `main` (`git checkout main && git pull`) and create the branch
   named in `docs/PLAN.md`.
2. **Explain the plan:** files to create or change, approach, and any decision not already
   in `docs/PLAN.md`. Wait for "go".
3. **Implement only this feature.** Update the READMEs with the sections listed for this
   feature in `docs/PLAN.md` (service-specific in `<service>/README.md`, cross-cutting in
   the root `README.md`), using real measured numbers where relevant. Never describe
   features that don't exist yet. Then run, for every service touched:
   `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`.
   Show the output. Everything must pass.
4. **Report back in the chat:** a file-by-file summary and the 2-3 most important lines or
   decisions, explained in plain words.
5. When the developer says "approved": commit, push, and open a PR with `gh pr create`.
   The PR description contains: What and why, How to test, Key decisions,
   Not included, Talking points (2-3 sentences on how to explain this feature in an
   interview).
6. **Stop.** The developer reviews and merges on GitHub. Do not merge PRs yourself.
7. **Never change anything outside the current feature on your own.** If you find a bug
   in earlier code or have an idea for a later feature, stop and tell the developer.

## Code rules

- Python 3.12. Each service is an independent uv project with its own `pyproject.toml`,
  `uv.lock`, `Dockerfile` and `tests/`. Services never import each other's code.
- Introduce infrastructure (Docker, compose services, dependencies, CI entries) only in
  the feature that first uses it.
- Tests with pytest. Tests must run without Docker (fake MQTT clients; moto for S3).
- PEP 8, enforced with ruff (default settings, line length 88).
- Configuration from environment variables, read into one frozen dataclass per service
  (`config.py`) with sensible defaults.
- Allowed dependencies: sensor `numpy`, `paho-mqtt`; processing `numpy`, `paho-mqtt`;
  sync `boto3`; dev `pytest`, `ruff`, `moto[s3]`. **Ask before adding anything else.**
- Type hints on public functions. Small functions. Comments explain why, not what.
- Use `logging`, not `print`. Randomness only via a seeded `numpy.random.Generator`.

## Design rules (never break these)

- The simulator is a generator yielding one sample at a time; pacing is separate.
- Ground truth goes on its own MQTT topic (`sensors/<id>/truth`). The detector never
  subscribes to it; only the evaluator does.
- Processing never touches the network except to receive MQTT samples. Its only output
  is the spool.
- Memory in the processing loop is bounded: nothing grows per sample or per window
  without a cap.
- Spool writes are atomic: write to `tmp/`, flush, `fsync`, `os.replace` into `ready/`,
  `fsync` the directory.
- After a successful upload, delete exactly the file that was uploaded, never "the oldest".
- S3 keys are deterministic from the batch file name, so retries never create duplicates.
- Shared files are the only coupling between services: any change to the spool format or
  the test fixtures updates `docs/spool-contract.md`, the example batch, and the fixtures
  in the same PR.
