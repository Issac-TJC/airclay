# Validation record

## Current evidence: October 21, 2026

The v1 dataset snapshot records six human-reviewed sessions from three participants,
with 59,913 frames and no formal train/validation/test split. Source hashes,
annotation acceptance, and the p03_s02 round-19 identity repair are recorded in
[data/manifests/airclay-v1](../data/manifests/airclay-v1). This establishes reviewed
recordings; it does not establish recognition accuracy or successful live sculpting.
See [DATA_HANDOFF.md](DATA_HANDOFF.md) for the data contract.

The current checkout contains implementation and test source for v1 control,
v2 previews, recording/review, learning, and optional plasticity. The older Blender
and training outputs listed below are not present in this checkout. Their values
are retained as historical reports, not current-version verification. Current runtime verification requires a new run or restored evidence matched to
the source version.

Human model comparisons, camera-to-display latency, current-version ten-minute
stability, and clean-environment reproduction remain unverified. Camera capture has
since produced the reviewed sessions; the old permission failure below does not
describe the device's current state.

The causal TCN branch added a 140-to-64 projection, three residual causal blocks with
dilations 1/2/4, and an 83,396-parameter four-class head. Tests cover output shape,
future-input invariance, checkpoint round trips, schema rejection, and the 23/24-frame
online warm-up boundary. Its reported two-epoch synthetic run validated plumbing only;
the three-seed human-data comparison remains pending.

## Historical reports

These entries summarize the earlier validation notes. Restore the original reports
and check their source version, configuration, and hardware before citing them as
experimental evidence. Files under `runs/` are ignored by Git and may not accompany
a checkout. The original notes dated the feature checks September 9–10, 2026; the
midterm draft also mentions a 57-test audit on October 19 whose log is absent here.

| Reported check | Reported result | Original evidence location |
|---|---|---|
| v1 baseline | 13 Python tests; 10,242-vertex sphere, 127 affected vertices; four committed operations, undo/redo, and timeout rollback | `runs/gui_test.json`, `runs/airclay_demo.blend` |
| MLP/GRU pipeline | Two-epoch synthetic training, checkpoint loading, and evaluation | `runs/smoke_mlp/`, `runs/smoke_gru/` |
| Causal TCN pipeline | Shape/causality/checkpoint tests and a two-epoch synthetic training/evaluation/replay smoke run; human results pending | `runs/smoke_tcn/` |
| hover2d | 41 Python tests; ten markers, first-surface/back-face checks, missing tips, packet rejection, and timeout | `runs/m1/hover_gui.json`, `runs/m1/python_tests.txt` |
| Simple hand preview | 51 Python tests; 42-joint projection, reflection, pinch, reuse, and cleanup | `runs/hand_preview/gui_test.json` |
| Realistic skin | 55 Python tests; skin/texture loading, reflection, fallback, and cleanup | `runs/realistic_hand/gui_test.json` |
| Smooth hand | 57 Python tests; welded mesh, pose continuity, style switching, guides, and package loading | `runs/smooth_hand/gui_test.json`, `runs/smooth_hand/package_test.json` |
| Native plasticity | 643-vertex proxy on a 10,242-vertex target; 330-frame compression/release and cache rebasing | `runs/plasticity/native_test.json` |
| Plasticity lifecycle | Default off, shape retention, cancel, undo/redo, loss pause, and save/load cleanup | `runs/plasticity/gui_test.json`, `runs/plasticity/load_test.json` |

Reported hover reprojection error was about 0.000492 pixels; hand-joint error was
about 0.017 pixels. These synthetic projection errors do not measure anatomical
fit or real-world tracking accuracy. The native plasticity test reported retained
maximum displacement about 0.437 and width changing from 2 to about 1.626 on the
unit sphere; it did not establish volume conservation.

Historical timing reports included about 16.4 ms for v1 send-to-apply, 3.2/14/20.6 ms
for simple/realistic/smooth hand updates, and 6.4/30.7 ms for numerical/GUI plasticity
updates. Test conditions differ. These values exclude camera capture and final
display, and must not be used as camera-to-display latency or compared as a common
benchmark. The midterm draft cites a separate v1 run at 16.479 ms under
`runs/plasticity/v1/gui_test.json`; that report is also absent here.

Earlier notes excluded `runs/track_latency.json` with `object_grip` and
`sculpt+object_grip` states because those outputs did not match the checked v1
source. Such logs cannot verify the currently exclusive controller.

## Historical environment notes

The earlier development machine was reported as Apple M4, macOS 26.6.2, Python
3.12.11, and Blender 5.2.1 LTS. The notes reported a MediaPipe 1.0.1 native crash and
successful 0.10.21 inference. They also recorded an upstream wheel-tag warning,
Blender Metal failures inside a sandbox, and an initial camera-permission failure.
These are machine-specific history, not freshly reproduced compatibility findings.
Current dependencies remain in `requirements.lock`; other platforms are unverified.

## Reproduction entry points

From the repository root, with `AIRCLAY_BLENDER` set to the executable:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_model.py
"$AIRCLAY_BLENDER" --background --factory-startup --python-exit-code 1 --python scripts/test_blender.py
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_gui.py -- --quit
"$AIRCLAY_BLENDER" --factory-startup --python-exit-code 1 --python scripts/test_hover_gui.py -- --quit
```

Hand and plasticity commands are described in [HAND_PREVIEW.md](HAND_PREVIEW.md)
and [PLASTICITY.md](PLASTICITY.md). GUI checks use synthetic input in independent
scenes: v1 port 8766, hover 8767, hand preview 8768, and plasticity 8769. Require
`passed:true` in their JSON reports; `--quit` or a zero exit code alone is not proof.
Save new results separately, with source hashes and configuration.

For human acceptance, record each finger, hand crossings/occlusion, entry/exit,
both dominant-hand roles, neutral re-arming, release, short-loss pause, long-loss
rollback, reconnection, undo/redo, and save. Also record ten-minute stability and
clean installation. Keep tester, time, source version, configuration, hardware,
and failure intervals with the evidence. Review of recorded labels alone does not
complete these interaction checks.
