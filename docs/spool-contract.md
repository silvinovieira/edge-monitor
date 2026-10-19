# Spool contract

The spool is the only coupling between `processing` (the writer) and `sync` (the
reader). Both run on the same device and share one directory. This document is the
format both sides code against. `docs/contract/example_batch.jsonl.gz` is a real batch
written by the current code. Processing's tests check that it matches both this
document and what the code writes today.

## Directories

```
<spool_dir>/
  tmp/     files being written; the reader never looks here
  ready/   complete batches, waiting for upload
```

- The writer creates a file in `tmp/`, writes it completely, flushes and `fsync`s it,
  moves it into `ready/` with `os.replace`, then `fsync`s `ready/`. A file in `ready/`
  is therefore always complete. A crash leaves at most one unfinished file in `tmp/`.
- On startup, the writer deletes everything in `tmp/`.
- The reader takes files from `ready/` only. After a successful upload it deletes
  exactly that file. It never renames, rewrites or reorders files.

## File names

```
{start_ns:019d}_{sensor_id}.jsonl.gz
e.g. 1767225600000000000_sensor-1.jsonl.gz
```

- `start_ns` is the wall-clock time of the batch's first sample, in nanoseconds since
  the Unix epoch. It's zero-padded to 19 digits, so sorting names sorts batches by
  time.
- `sensor_id` contains only letters, digits and `-`. `_` is the separator.
- The name is a pure function of the batch, with no counter and no random part. A
  batch written twice (for example, regenerated after a crash) replaces itself instead
  of becoming a duplicate. The reader can derive a stable upload key from the name.

## Content

The file is gzip-compressed UTF-8 text with one JSON object per line, in this order:

1. One `header` line.
2. Zero or more `window` lines, oldest first.
3. One `samples_10hz` line.

All times are integers in nanoseconds since the Unix epoch. Every interval is
half-open: `[start_ns, end_ns)`.

### `header`

| Field | Type | Meaning |
|---|---|---|
| `type` | string | `"header"` |
| `version` | int | format version, currently `1` |
| `sensor_id` | string | same as in the file name |
| `start_ns` | int | time of the first sample in the batch |
| `end_ns` | int | time just after the last sample in the batch |
| `sample_rate_hz` | int | sample rate of the raw stream |
| `window_size` | int | samples per feature window |
| `hop_size` | int | samples between two windows |

A batch normally covers 60 s. The last batch before a shutdown can be shorter.

### `window`

One line per feature window whose end falls inside the batch, so
`header.start_ns < end_ns <= header.end_ns`. A window can start before the batch,
because windows overlap.

| Field | Type | Meaning |
|---|---|---|
| `type` | string | `"window"` |
| `start_ns` | int | time of the window's first sample |
| `end_ns` | int | time just after the window's last sample |
| `rms` | float | root mean square of the acceleration |
| `mean` | float | mean acceleration |
| `std` | float | standard deviation of the acceleration |
| `peak_hz` | float | dominant frequency |
| `is_anomaly` | bool | the detector's flag for this window |

### `samples_10hz`

The raw stream reduced to 10 points per second. Point `i` covers
`[start_ns + i·interval_ns, start_ns + (i+1)·interval_ns)`.

| Field | Type | Meaning |
|---|---|---|
| `type` | string | `"samples_10hz"` |
| `start_ns` | int | equal to `header.start_ns` |
| `interval_ns` | int | `100000000` (100 ms) |
| `mean` | list of float | mean acceleration of each point |
| `rms` | list of float | RMS acceleration of each point |

`mean` and `rms` have the same length, `(header.end_ns − header.start_ns) / interval_ns`:
600 for a full 60 s batch.

## Versioning

- **Adding** a field or a new line `type` is backward compatible and keeps the version.
  Readers must ignore fields and line types they don't know.
- **Removing, renaming or changing the meaning** of anything bumps `version`. Readers
  must reject a version they don't support, leaving the file in `ready/`, and log it.
- Any change updates this document, `docs/contract/example_batch.jsonl.gz` (from
  `processing/scripts/make_example_batch.py`), and the tests of every service that
  reads it, in the same PR.
