# AirClay shared dataset

This release contains reviewed human recordings at their original sampling times.
All six v1 sessions were confirmed to use capture `smoothing=1.0`: no application-level
EMA was applied. MediaPipe's internal temporal processing remains present. No extra
filter, resampling, interpolation, normalization, augmentation, or training windows
are added by this export. The current release has three participants and no formal
train/validation/test split. Freeze the shared participant split after all five
participants are available.

## Receive and read

Download `airclay-data-v1.zip` from the team's shared storage. From the repository root:

```bash
mkdir -p data/processed
unzip /path/to/airclay-data-v1.zip -d data/processed
.venv/bin/python data/processed/airclay-v1/read_handoff.py data/processed/airclay-v1 --verify
```

The standalone reader only requires Python and NumPy; it does not need PyTorch,
MediaPipe, a camera, or Blender. For another release, replace `v1` with its version.

The optional `airclay-videos-v1.zip` contains only the six reference videos. Extract
it into the same `data/processed` directory to add videos to the existing sessions.
Use `--verify --videos` to verify both core files and videos. The archives share one
top-level `airclay-v1` folder; do not create an extra nested copy of that folder.

The Git snapshot at `data/manifests/airclay-v1/archives.json` records the archive hashes
and the package manifest hash. The package manifest records each payload's SHA-256.
`--verify` detects missing or changed core payloads. Paths inside the release are
relative to the package root, so it can be moved to another machine.

Each `data/<subject>_<session>/` contains the four existing AirClay files
(`metadata.json`, `frames.jsonl`, `annotations.json`, `recording_takes.json`) and
`landmarks.npz`. Existing AirClay recording readers can read that session directory.
The recording-takes manifest retains rejected attempt records for provenance;
their frames and videos are not exported as samples. `manifest.json` identifies the
accepted timeline and source hashes. `inventory.csv` summarizes the six sessions.

## NumPy interface

With the package reader on the Python import path:

```python
from pathlib import Path
import sys

root = Path("data/processed/airclay-v1")
sys.path.insert(0, str(root))
from read_handoff import load_session, iter_takes

arrays, metadata = load_session(root, "p01_s01")
for take_id, take in iter_takes(arrays):
    t_seconds = take["timestamp_ms"] / 1000
    left_valid = take["valid"][:, 0]
    left_index_tip = take["image"][:, 0, 8, :2]
    observed = left_index_tip[left_valid]
```

Use `np.load(path, allow_pickle=False)` for direct loading. `N` is the number of
original frames, not a synthetic 30 Hz timeline. Hand slot 0 is physical Left and
slot 1 is physical Right, regardless of the dominant hand or screen position.

| Array | Shape / dtype | Meaning |
|---|---|---|
| `image`, `world` | `[N, 2, 21, 3]`, float64 | Original coordinate values in assigned hand slots |
| `present` | `[N, 2]`, bool | A hand record exists in the source frame |
| `valid` | `[N, 2]`, bool | Present hand is marked valid by the source |
| `score` | `[N, 2]`, float64 | Original handedness score, not a per-landmark confidence |
| `detector_side` | `[N, 2]`, Unicode | Original detector category; never use it to reorder slots |
| `timestamp_ms` | `[N]`, float64 | Canonical session time, with pauses and rejected takes removed |
| `capture_timestamp_ms` | `[N]`, float64 | Original monotonic capture clock; not wall-clock time |
| `frame_index` | `[N]`, int64 | Zero-based row in the canonical recording and reference video |
| `label` | `[N]`, int8 | 0=idle, 1=sculpt, 2=orbit, 3=resize |
| `take_index` | `[N]`, int32 | Index into `take_ids` |
| `take_ids` | `[K]`, Unicode | Accepted take names in temporal order |

Missing hands have NaN coordinates/scores, an empty detector category, and false
presence/validity. Existing invalid observations, if any, keep their coordinates
with `valid=false`. Always use the validity mask; do not fill missing hands and then
count them as real detections. Coordinate values are not clipped or mirrored.
`image` x/y use normalized image coordinates; z is the original MediaPipe relative
depth output, not image pixels. `world` preserves the original hand-local MediaPipe
coordinates and is not a calibrated shared camera-space position for the two hands.

Labels use `[start_ms, end_ms)` intervals; uncovered time is idle, matching the
existing reader. `annotations.json` retains the exact event boundaries: use it for
event analysis rather than treating frame-aligned labels as more precise ground truth.
Video playback seconds can differ from acquisition time. Match video frame indices
to `frame_index`, then use `timestamp_ms` for labels and event measurements.

## Processing contract

Xinyu should derive None/EMA/Kalman from the same assigned coordinates, timestamps,
labels and validity masks. Reset filter state at every session and take boundary,
and after long losses according to the shared filter implementation. Use observed
time intervals for time-dependent filters; do not assume a capture rate of 30 Hz.
Do not drop missing frames or join separate takes into one continuous motion.

For the main model comparison, use the same EMA variant (alpha=0.45) once Xinyu's
offline/online preprocessing is agreed. Current training/evaluation does not
automatically add EMA to these files. Resampling, feature extraction and 24-frame
windows come afterward; no window may cross a session or take boundary. Keep both
sessions of each person in the same eventual split. Never tune filters or models
on held-out test participants.

`effective_fps` is frame count divided by accepted-timeline duration; median capture
interval excludes take boundaries. Missing fractions use all original frames.
Per-class duration is measured from annotation intervals, and active event counts
merge adjacent intervals of the same class. The configured 30 FPS is reported
separately and is not an observed capture-rate measurement.

p03_s02 round 19 uses the already corrected Left/Right dictionary slots. The original
detector category remains unchanged. The core package includes the repair log and
pre-repair frame file under `provenance/p03_s02/`; it is an audit backup, not another
training session. Human acceptance and source hashes are recorded in provenance.

## Rebuild and share

From the repository root, with all input annotations already verified:

```bash
.venv/bin/python scripts/prepare_handoff.py \
  --sessions p01_s01 p01_s02 p02_s01 p02_s02 p03_s01 p03_s02 \
  --reviewed-by "Zhijian Wang" --capture-smoothing 1.0 --version v1
```

Existing outputs are never overwritten. For a new release, provide a new version
and explicitly list its sessions. This exporter currently accepts complete guided,
unmirrored human sessions with reference videos and confirmed capture smoothing=1.0.
It validates inputs, writes portable arrays, checks the source hashes and produces:

- `data/processed/airclay-v1/`: full core dataset and standalone reader.
- `data/manifests/airclay-v1/`: small Git snapshot of labels, metadata, statistics,
  provenance, hashes and archive receipts.
- `dist/airclay-data-v1.zip` and `dist/airclay-videos-v1.zip`: files to send through
  shared storage. Neither archive is committed to Git.

Commit the exporter, reader, tests, this guide and the manifest snapshot. Share the
archives separately. Do not add full JSONL recordings, NumPy archives, video files,
or pre-repair coordinate backups to the Git snapshot. No data is uploaded by these scripts.
