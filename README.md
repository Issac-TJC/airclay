# AirClay

AirClay uses an RGB webcam and MediaPipe landmarks to control a mesh in Blender.
The dominant hand sculpts, the other hand orbits the view, and a two-hand pinch
changes the brush radius. Rules, MLP, GRU, and causal TCN backends share the same controller.
MediaPipe is a fixed front end; the trained models classify interaction intent.

## Setup and quick start

Run commands from the repository root. The development setup uses Python 3.12,
macOS Apple Silicon, and Blender 5.2. Other platforms have not been verified.

```bash
AIRCLAY_PYTHON="$(command -v python3.12)" bash scripts/bootstrap.sh
.venv/bin/airclay doctor
```

The bootstrap script installs `requirements.lock`, the command launcher, and the
landmark model. Set `AIRCLAY_PYTHON` to your Python 3.12 executable; the script's
fallback path belongs to the original development machine. `doctor` checks
packages, paths, and the UDP port without opening the camera.

Start Blender in one terminal and tracking in another:

```bash
bash scripts/start_blender.sh
```

```bash
.venv/bin/airclay track --backend rules
```

The launcher uses the macOS Steam Blender path by default. Set `AIRCLAY_BLENDER`
to a different executable if needed. It opens a fresh scene, creates a clay sphere,
and starts the receiver. Controls are in **N > AirClay**. Press Q in the camera
window to stop tracking, or Esc in Blender to stop receiving. On macOS, grant
camera access to the terminal used to launch the tracker.

For a camera-free demonstration, replace `track` with:

```bash
.venv/bin/airclay simulate
```

This sends a roughly 13-second sequence with two sculpt edits, orbit, and brush
resize. Use **Create clay sphere** for a new target before repeating it.

## Controls

Right is the default dominant hand. Open both hands to arm the controller on
connection and after each operation.

| Action | Gesture or control |
|---|---|
| Position the brush | Move the dominant index finger |
| Sculpt | Pinch the dominant hand, wait about 0.2 s, then move; release to commit |
| Orbit the view | Pinch and move the other hand |
| Resize the brush | Pinch both hands within about 0.2 s, then move them apart or together |
| Undo / redo | AirClay panel, or Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z while receiving |
| Save | Blender File > Save As |

Modes are exclusive and stay locked until release. A missing required hand pauses
the operation; 300 ms of sustained loss or stream timeout cancels the unfinished
edit. Sculpting follows a fixed view plane. Rotate the view before editing from
another direction. Orbit changes the view, and resize changes brush radius.

The default sphere has 10,242 vertices and radius 1. Brush radius is 0.08–0.60,
maximum displacement per sculpt operation is 0.5, and history holds 30 operations.
Repeated large edits can stretch the mesh; the sculpt tool has no remeshing.

## Optional previews

Use one of these configurations with the same Blender receiver:

```bash
.venv/bin/airclay --config configs/hover.json track --backend rules
.venv/bin/airclay --config configs/hands.json track --backend rules
```

Run one tracker at a time. Both configurations also support `simulate` and
`replay <recording>`.

- **hover2d:** ten surface candidates, with Left blue and Right orange.
  T/I/M/R/P identify the fingers. Dashed circles indicate the first visible surface
  under each fingertip; they do not indicate contact. Missing or out-of-frame
  fingertips and stream timeouts hide the markers.
- **hand_preview:** a 21-joint skeleton drives Smooth blue hand (default),
  Realistic skin, or Simple joints. OPEN/PINCH/LOST reports pose only. Display depth
  is manual, and **Flip hand front/back** changes local depth without changing
  screen position or hand identity.

These UDP v2 profiles bypass intent classification. The separate **Plastic
collision (experimental)** switch can enable fingertip deformation in hand
preview; it is off by default and uses a manual collision plane. See
[protocol](docs/PROTOCOL_V2.md), [hand preview](docs/HAND_PREVIEW.md), and
[plasticity](docs/PLASTICITY.md) for details. Restart the tracker when changing
protocol or profile; each change requires a new session.

## Record and review data

Follow the [recording guide](data/README.md). For data that can be filtered later:

```bash
.venv/bin/airclay --config configs/record_raw.json record \
  --subject p01 --session s01 --guided --video --output data
```

This disables application-level EMA while retaining MediaPipe's internal
processing. Use unique subject/session IDs. The instruction window must be
completed before capture starts. Guided recording defaults to 20 rounds of
sculpt, orbit, and resize, followed by two minutes of natural movement. At each
pause, R retries the round and N accepts it. Q/Esc discards the entire current
recording; a complete run saves automatically. Add `--interact` to drive Blender
from the same camera stream. Retrying a recording round does not undo Blender edits.

Review reference video and edit labels with:

```bash
.venv/bin/airclay review data/p01_s01 data/p01_s02
.venv/bin/airclay annotate data/p01_s01
```

The reviewer plays each round using landmark timestamps. Space pauses, N/P changes
round, R repeats, A/D steps frames, +/- changes speed, and Tab changes session.
F saves an issue marker in `human_review_flags.jsonl`; it does not change labels or
verification. The annotator uses I/O to select an interval, 0–3 for
idle/sculpt/orbit/resize, V to toggle verification, and S to save with a backup.
Prompt labels need human review before training or evaluation.

New capture keeps the camera's original orientation (`mirrored=false`). Check
physical Left/Right in the preview before recording. Dominant-hand settings assign
control roles; they do not swap identities. Existing recordings are not converted.

## Shared data and experiments

The v1 handoff contains six reviewed sessions from three participants (59,913
frames). It has no formal split. The pilot plans five participants, two sessions
each, with a shared 3/1/1 subject split. See the [handoff guide](docs/DATA_HANDOFF.md)
for the separate archives and NumPy interface, and the
[experiment protocol](docs/EXPERIMENTS.md) for labels and metrics.

Once all five participants are available, create a split and train the baselines:

```bash
.venv/bin/airclay split data --output data/split.json --seed 42
.venv/bin/airclay train --model gru --split data/split.json --output runs/gru_seed42
.venv/bin/airclay train --model mlp --split data/split.json --output runs/mlp_seed42
.venv/bin/airclay train --model tcn --split data/split.json --output runs/tcn_seed42
```

**Training and evaluation use the coordinates stored in each recording. They do
not add EMA.** Preserve raw recordings and derive filter variants later. An EMA
comparison requires consistent offline and online preprocessing before these runs.
The split command reads immediate session folders; for extracted handoff data, use
`data/processed/airclay-v1/data` as the data root. All backends must use the same split.

Defaults are CPU, a 24-frame window, at most 50 epochs, and validation Macro-F1 early
stopping. The GRU has two 128-unit layers; the MLP uses the last frame's 135 static
features. The TCN projects 140 features to 64 channels and uses three residual causal
blocks with two kernel-3 convolutions per block and dilations 1, 2, and 4. All learned
backends wait for a full window before predicting. Repeat
training with seeds 43 and 44 for the planned comparison. `--allow-small` permits a
three-person smoke split; it is not the planned pilot split.

```bash
.venv/bin/airclay evaluate --backend rules --split data/split.json --output runs/eval_rules
.venv/bin/airclay evaluate --backend gru --checkpoint runs/gru_seed42/best.pt --split data/split.json --output runs/eval_gru
.venv/bin/airclay evaluate --backend mlp --checkpoint runs/mlp_seed42/best.pt --split data/split.json --output runs/eval_mlp
.venv/bin/airclay evaluate --backend tcn --checkpoint runs/tcn_seed42/best.pt --split data/split.json --output runs/eval_tcn
.venv/bin/airclay track --backend gru --checkpoint runs/gru_seed42/best.pt
.venv/bin/airclay track --backend tcn --checkpoint runs/tcn_seed42/best.pt
.venv/bin/airclay replay data/p01_s01 --backend rules
.venv/bin/airclay replay data/p01_s01 --backend tcn --checkpoint runs/tcn_seed42/best.pt
```

Evaluation writes `metrics.json` and `confusion.png`. Tune with `--partition val`;
the default is test. Learned backends require a compatible checkpoint. Replay uses
recorded landmarks and source timing; it does not rerun MediaPipe or add smoothing.

For the frozen three-seed TCN experiment, provide the shared split and the EMA 0.45
`derived_manifest.json` produced by `scripts/derive_filtered.py`. A legacy flat
manifest with `filter`, `alpha`, and recording paths is also accepted:

```bash
.venv/bin/python scripts/run_tcn_midterm.py \
  --split data/split.json \
  --preprocessing-manifest data/processed/airclay-v2-ema/derived_manifest.json \
  --device cuda \
  --output runs/midterm/tcn
```

The runner rejects synthetic or unverified recordings, subject leakage, incomplete
training classes, and a non-empty output directory. It trains seeds 42, 43, and 44,
evaluates validation before test, and writes the aggregate summary and failure intervals.

## Packaging and reference

```bash
.venv/bin/python scripts/package_addon.py
```

Install `dist/airclay_blender.zip` through Blender's **Install from Disk**. The
launcher loads the add-on temporarily without changing preferences. Camera and
training dependencies stay in the external environment.

Put global configuration before the subcommand:
`airclay --config configs/my_config.json track`. Overrides merge with
`configs/default.json`. The local receiver reads that default file; the packaged
add-on uses built-in defaults. Dependencies are pinned in `requirements.lock`;
model source and checksum are in `assets/model_manifest.json`.

- [Implementation](docs/PLAN.md): data flow, features, controller, and geometry.
- [Roadmap](docs/IMPLEMENTATION_CHECKLIST.md): current status and future milestones.
- [Validation record](docs/VALIDATION.md): available evidence and pending checks.
