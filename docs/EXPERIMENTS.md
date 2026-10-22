# Data and experiments

## Current dataset and planned split

The v1 handoff has six reviewed sessions from p01, p02, and p03, with 59,913 frames.
No formal split is frozen. The midterm pilot plans five participants with two
sessions each, split 3/1/1 by subject using seed 42. Keep both sessions of a person
in the same partition. One held-out participant supports a pilot result, not a
broad claim about unseen users.

Use [data/README.md](../data/README.md) for collection and
[DATA_HANDOFF.md](DATA_HANDOFF.md) for the shared archives. Each guided session
contains 20 rounds of sculpt, orbit, and resize, plus two minutes of natural
movement. Report actual counts and capture rates from the inventory, rather than
assuming the configured 30 FPS was achieved.

## Recording format

Each `data/<subject>_<session>/` contains:

| File | Contents |
|---|---|
| `metadata.json` | Version, subject/session IDs, dominant hand, configured FPS, synthetic/mirrored flags, creation time, and guided settings when used |
| `frames.jsonl` | Strictly increasing millisecond timestamps and per-hand 21 × 3 image/world arrays |
| `annotations.json` | `verified` and non-overlapping `[start_ms, end_ms)` label intervals |
| `reference.mp4` | Optional reference video, one encoded frame per recorded sample |
| `recording_takes.json` | Guided attempts, decisions, completeness, frame counts, and accepted timeline ranges |

Completed guided sessions retain attempts under `takes/round_XX_take_YY/` and
natural movement under `takes/natural/`. The root timeline includes accepted takes
only. Pauses and rejected takes are excluded; within-take timing is preserved.
Frames retain `capture_timestamp_ms` and `take_id`. Take directories are not
independent sessions. Shared exports omit rejected-attempt samples.

Capture begins after the instruction window's final Continue. In-progress files
live under `.inprogress/`. A complete run publishes the session; Q/Esc discards the
current session, including accepted rounds. Other interruptions retain recovery
files. Free recording saves at `--seconds` or S; its initial labels are all idle.

New capture uses the original camera orientation and records `mirrored=false`.
Legacy frames without that flag retain the earlier mirrored coordinate convention
in replay. Check and reconcile orientation before combining datasets.

Video is encoded at the configured frame rate, which can differ from acquisition
cadence. Match video frame indices to recorded frames, then use landmark timestamps
for labels and event measurements. Uncovered annotation time is idle. S in the
annotator saves the previous labels to `annotations.previous.json`; V only records
human confirmation.

## Labels

| Label | Start | End |
|---|---|---|
| idle | No intended operation | An active intent begins |
| sculpt | Intended dominant-hand pinch to edit | Intended release |
| orbit | Intended auxiliary-hand pinch to orbit | Intended release |
| resize | Intended two-hand pinch combination | Intended release of either hand |

Label intended actions from the recording, not rule-trigger times. Include natural
motion, incidental finger contact, crossings, speed changes, and brief occlusion.
Review ambiguous boundaries with another team member. The video reviewer can flag
issues but does not edit labels or set `verified`; use the annotator for those steps.

## Preprocessing and model comparison

Retain identity-assigned raw recordings with capture `smoothing=1.0`. This disables
application-level EMA, while MediaPipe's internal temporal processing remains.
Derive None, EMA, and Kalman variants later from the same coordinates, validity,
labels, and timestamps. Reset filters at session/take boundaries and after long
losses; use observed time intervals and keep missing hands invalid.

The planned main comparison uses EMA with alpha 0.45. Consistent offline/online
filtering still needs to be integrated: current training, evaluation, and replay
use stored coordinates without adding EMA, while default live tracking applies it.
Resampling and feature/window extraction follow filtering. Existing resampling,
velocities, and learned windows reset at take boundaries; no training window crosses
a take. The controller and event scorer currently run across the accepted session
timeline rather than resetting separately for each take.

Rules, MLP, and GRU use the same data, split, sampling rate, and controller. TCN
comparisons remain planned. Tune rule thresholds and filter parameters on
validation data only. Train learned models with seeds 42, 43, and 44; report means
and standard deviations with each run's results retained. Seed variation is not
variation across independent participants. Freeze settings before test evaluation.

### Filtered releases

`scripts/derive_filtered.py` writes a filtered copy of a handoff release. Only landmark
coordinates change; hand identities, timestamps, takes, validity, and labels are
copied. Filters reset at every take and after gaps of 150 ms or more. EMA uses alpha
0.45 with the same update as live `HandMatcher`, but keeps the release's hand
identities instead of re-matching hands; `--check-online` reports how often the two
differ. Kalman uses a constant-velocity model with r=9e-6 and q=3e-3, with q chosen on
the validation subject only.

```bash
.venv/bin/python scripts/derive_filtered.py data/processed/airclay-v1 data/processed/airclay-v1-ema --filter ema
.venv/bin/python scripts/derive_filtered.py data/processed/airclay-v1 data/processed/airclay-v1-kalman --filter kalman --q 3e-3 --r 9e-6
```

To train or evaluate on a filtered release, build a split from its `data/` folder.
Split files store absolute paths, so build one on each machine. Seed 42 gives the same
subject split as the raw release.

```bash
.venv/bin/airclay split data/processed/airclay-v1-ema/data --allow-small --seed 42 --output data/split_ema.json
.venv/bin/airclay evaluate --backend rules --split data/split_ema.json --partition test --output runs/eval_rules_ema
```

`scripts/filter_eval.py` runs the same rule-backend evaluation but filters in memory,
so settings can be compared without writing new releases. Give it a split of the raw
release, built the same way from `data/processed/airclay-v1/data`; an EMA split would
be smoothed twice.

```bash
.venv/bin/python scripts/filter_eval.py --split data/split.json --partition val --filter kalman --q 1e-5 3e-5 1e-4 3e-4 1e-3 3e-3 1e-2 3e-2 1e-1
.venv/bin/python scripts/filter_eval.py --split data/split.json --partition test --filter none
.venv/bin/python scripts/filter_eval.py --split data/split.json --partition test --filter ema
.venv/bin/python scripts/filter_eval.py --split data/split.json --partition test --filter kalman --q 3e-3
.venv/bin/python scripts/filter_eval.py --split data/split.json --partition test --filter ema --set combo_ms=0
```

## Implemented metrics

Classification is computed at resampled timestamps for idle/sculpt/orbit/resize.
`classification` contains raw predictions; `state_classification` contains controller
outputs. The confusion matrix uses raw predictions. Event metrics use controller
outputs and resampled truth labels.

- Consecutive non-idle samples of the same class form an event.
- In chronological truth order, each event is greedily matched to the unused
  same-class prediction with the greatest positive overlap.
- Unmatched predictions are false operations; unmatched truth events are misses.
  False operations per minute uses the full evaluated time span, including idle.
- `wrong_mode_segments` counts predicted events overlapping a different truth class.
- Early release means a matched prediction ends more than 100 ms before truth.
- Onset/offset delay is predicted minus true boundary. Negative values mean early
  activation/release. Medians exclude unmatched events, so report misses alongside them.

These are the evaluator's definitions, not a standard benchmark protocol. Keep the
original annotation intervals for analyses that need finer timing than the 30 Hz grid.

## Planned Blender task and timing

Use the same unit sphere, initial view, and brush radius. Ask each participant to
make two protrusions, orbit the view, resize the brush, make another edit, undo once,
and save. The midterm plan is a rule-based pilot with equal practice time. Record
completion time, success, extra undo operations, wrong modes, and failure cases.
A later model comparison should counterbalance backend order across participants.

`track --seconds 600 --output runs/ten_minute.json` records timing and mode logs,
not images. The v1 receiver writes `runs/blender_latency.json` when stopped in a
project checkout. Tracker `classifier_ms` includes resampling, classification,
controller work, and sending. Receiver `transport_apply_ms` starts at send time;
`capture_apply_ms` starts at the resampled input timestamp. Neither measures
physical gesture onset to visible screen response, and preview timing does not
include the later plasticity update in the timer tick.

Measure camera-to-display latency independently. The goals of at least 20 Hz and
median latency below 250 ms remain unverified. Manual checks should cover arming,
two-hand arbitration, mode locking, brief/long hand loss, stream interruption,
reconnection, both dominant-hand choices, crossings, undo/redo, and saving.
