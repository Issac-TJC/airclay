# Implementation checklist

Updated: October 21, 2026.

Checked items below mean the implementation exists in the source. Runtime and human
acceptance are tracked separately in [VALIDATION.md](VALIDATION.md); historical
results do not verify every later change. Synthetic inputs establish software
behavior, not recognition accuracy or calibrated depth.

## Current baseline

- [x] External Python environment, MediaPipe model manifest, launcher, and add-on packaging.
- [x] `doctor`, `track`, `simulate`, `record`, `review`, `annotate`, `split`, `replay`, `train`, and `evaluate` commands.
- [x] Two-hand landmark tracking with handedness/wrist matching and configurable EMA.
- [x] Original camera orientation (`mirrored=false`), stable fingertip IDs, and Left-blue/Right-orange markers.
- [x] Causal resampling and common feature extraction for learning and inference.
- [x] Rules, single-frame MLP, 24-frame GRU, and strictly causal 24-frame TCN intent backends.
- [x] Exclusive v1 controller with neutral re-arming, onset arbitration, mode locking, loss pause, and rollback.
- [x] Surface ray selection, geodesic brush weights, planar sculpting, view orbit, and brush resize.
- [x] Thirty-operation AirClay undo/redo history and timeout rollback.
- [x] Guided rounds with accept/retry, reference video review, manual labels, and subject splits.
- [x] Portable raw-data export and NumPy reader; v1 contains three participants and six reviewed sessions.
- [x] Frame classification, controller classification, confusion matrix, and event metrics.
- [ ] Complete the five-person dataset and freeze the shared 3/1/1 subject split.
- [ ] Add common offline/online preprocessing for later None/EMA/Kalman comparisons.
- [ ] Complete human baseline training, evaluation, and the fixed Blender task.
- [ ] Record current-version camera/Blender recovery and ten-minute stability checks.
- [ ] Reproduce installation and operation on a second machine or clean environment.

Changing the dominant hand changes control roles. It must not swap anatomical hand
slots, fingertip IDs, or marker colors. Human checks must include both dominant-hand
settings, crossings, occlusion, fast entry/exit, and a temporarily missing hand.

## Planned interaction

The longer-term design lets the dominant index finger sculpt while the auxiliary
hand grips, rotates, and uniformly scales the object. Auxiliary grip requires all
five fingertips to contact the surface. Rotation follows the hand's pose; scaling
uses thumb/index 3D separation. Object scale and brush radius remain separate.
This behavior is not provided by the current v1 `orbit` and `resize` modes.

The proposed camera coordinates are +x right, +y up, and +z away from the camera.
Movement toward the camera therefore has negative delta-z. These conventions apply
to the planned calibrated representation, not the current hand-local landmarks.

## Milestones

### M0: Preserve the v1 baseline

- [x] Existing source and tests cover the exclusive controller, v1 packets, and planar tools.
- [ ] Retain source-matched results when rerunning the baseline; historical `runs/`
  records must be identified by their own version and conditions.

### M1: Ten-finger 2D hover

- [x] Explicit v2 `hover2d` profile with full fingertip snapshots and a 4096-byte limit.
- [x] Hidden/hover markers, first-hit ray selection, and rejection of back-facing hits.
- [x] Finger IDs, identity colors, view-dependent marker size, and display toggles.
- [x] Existing tests cover projection, missing/out-of-frame tips, invalid packets,
  session changes, timeouts, and preservation of the target during plain preview.
- [ ] Record human checks for each finger, crossings/occlusion, and dominant-role changes.

[PROTOCOL_V2.md](PROTOCOL_V2.md) defines this implemented subset. It has no contact,
latched state, camera-space depth, or concurrent operations.

### M2: Depth and contact anchors

- [ ] Save camera intrinsics, resolution, distortion, calibration date, and calibration ID.
- [ ] Calibrate palm scale at about 30, 45, and 60 cm and implement geometric wrist depth.
- [ ] Compare geometric depth with Depth Anything V2 and a hand-specific depth regressor
  trained on RHD and a fixed InterHand2.6M subset. Preserve source versions and sample IDs.
- [ ] Combine root depth with local hand structure to produce ten camera-space tips,
  validity, confidence, and a documented camera-to-Blender transform.
- [ ] Add causal depth filtering, speed limits, outlier rejection, and explicit 2D fallback.
  Low-confidence depth must not create five-finger contact.
- [ ] Extend recording and transport with calibration IDs, units, raw/filtered depth,
  and confidence. Use a new explicit profile or version for operational packets.
- [ ] Implement contact only after valid tracking, first visible front-facing hit,
  and a calibrated surface-gap check. Proposed entry is `|g| <= 0.06R` for three
  frames; exit is beyond `0.10R` or invalid tracking for five frames.
- [ ] Store anchors in object-local coordinates with face/barycentric coordinates,
  hand/finger ID, timestamp, and confidence. Latch the first contact rather than
  switching to a rear surface during penetration.
- [ ] Verify projection, axes, units, static jitter, forward/backward direction,
  hysteresis, occlusion recovery, and stable ten-second contact.

Initial targets are depth jitter below 1.5 cm and at least 90% direction accuracy
over 30 forward/backward trials. Calibration and evaluation sequences must differ.
Report depth/displacement error, valid coverage, jitter, lag, and runtime. Report
MPJPE only if the implementation produces joints with a defined coordinate/alignment
protocol. Targets are provisional and have not been measured.

### M3: Five-finger grip, rotation, and object scale

- [ ] Enter grip after all auxiliary fingertips maintain contact for at least 150 ms.
- [ ] Save the initial anchors, fingertips, palm basis, center, rotation, and scale.
- [ ] Estimate rotation from weighted Kabsch alignment and palm orientation; smooth
  quaternions, preserve sign continuity, and limit angular speed.
- [ ] Rotate about the object's center without translating it. Freeze on brief
  fingertip loss; end/cancel after exit hysteresis rather than falling back to one finger.
- [ ] Scale uniformly from `s0 * clamp(d/d0, 0.5, 2.0)`, with a proposed 3% deadband,
  filtering, and speed limits. Define depth-loss behavior before enabling fallback.
- [ ] Derive rotation and scale from the onset snapshot to avoid accumulated drift.
  Keep `object_scale` distinct from `brush_radius` in the protocol, UI, and logs.
- [ ] Check known 5/15/45-degree rotations, pure translation, pure scale,
  near-coplanar points, abnormal tips, and front/back hand poses.
- [ ] Compare target-angle tasks with v1 orbit; record time, angle/scale error,
  overshoot, missed triggers, and false triggers. The initial synthetic angle-error
  target is median below 3 degrees; include repeated human enlargement/reduction trials.

### M4: Concurrent sculpting and object transforms

- [ ] Replace the exclusive label with channels such as `sculpt_active`,
  `object_grip_active`, and `brush_resize_active`, sharing a contract across backends.
- [ ] Use independent hand/channel timing and explicit role conflicts. Auxiliary
  rotation/scale must not terminate dominant-hand sculpting.
- [ ] Apply object transforms first, then map the sculpt point into updated local
  coordinates. Define how world brush radius behaves under object scale.
- [ ] Use one compound transaction covering mesh, object transform, view, and brush;
  commit when all channels finish and roll back the whole transaction on timeout.
- [ ] Add overlapping labels, compound transaction IDs, per-channel state, calibration,
  units, and fallback flags. Preserve explicit v1 compatibility.
- [ ] Validate the mode truth table, loss handling, packet loss/order/duplication,
  anchor stability during a 90-degree rotation, and deterministic replay.
- [ ] Check simultaneous sculpt/rotate/scale for 30 seconds, atomic undo/redo,
  saving/reopening, and ten minutes of continuous transport.

The receiver remains responsible for mesh hits and anchors, with all Blender calls
on the main thread. UI/logs should expose channels, depth source/confidence,
fallback state, anchor information, and timing by stage.

### M5: Public-data pretraining and few-shot adaptation

- [ ] Record dataset versions, licenses, hashes, and fixed subset IDs. Implement
  adapters that retain source labels and distinguish coordinate systems.
- [ ] Pretrain temporal representations on public motion data and implement
  prototype adaptation with 1/5/10 independently recorded demonstrations per command.
- [ ] Keep support/query and train/validation/test separated before window generation.
- [ ] Compare rules, MLP, scratch GRU, pretrained linear classification, and prototype
  adaptation using the same data and evaluation budgets.
- [ ] Add multi-label training and evaluation if concurrent controls are included.
- [ ] Report per-class and macro metrics, continuous-operation errors, rejection,
  latency, and variation across users and seeds; exclude synthetic smoke results.

The midterm TCN implementation is complete, including checkpoint validation, causal
output tests, CPU profiling, and a three-seed experiment runner. Human TCN training
and the filter comparison remain near-term tasks. They do not establish public-data
pretraining, few-shot learning, or calibrated depth.

### M6: Final delivery

- [ ] Complete the fixed Blender task with the planned participants and record failures.
- [ ] Report measured recognition, event, depth (if implemented), timing, and task results.
- [ ] Save source/configuration/model/calibration IDs, initial object state, and hardware.
- [ ] Finish stability and clean-install checks, package the add-on, and save a demo
  scene and video. Align the report and documentation with the delivered behavior.

## Independent optional extensions

These extensions do not replace M2–M4 calibration, contact, or concurrent-control
requirements, and are not prerequisites for those milestones.

### Hand preview

- [x] `hand_preview` carries both 21-joint skeletons and local articulation.
- [x] Smooth, realistic, and simple hand models reuse meshes and support visibility,
  manual depth, front/back reflection, and OPEN/PINCH/LOST feedback.
- [x] Asset manifests, textures, attribution, fallback, and cleanup are implemented.
- [x] Existing synthetic tests cover projection, poses, reflection, style switching,
  direction guides, resource lifetime, and target preservation.
- [ ] Record human fit, extreme poses, crossings, and long-session behavior.

See [HAND_PREVIEW.md](HAND_PREVIEW.md). Both Smooth meshes are blue; identity is
shown by the blue/orange cursors and legend.

### Plastic collision

- [x] Default-off native fingertip Collision spheres and an isolated Soft Body proxy.
- [x] Manual depth/size, outside-first arming, loss pause, and shape retention.
- [x] Cancel, whole-experiment undo/redo, bounded cache, and save/load cleanup.
- [x] Numerical, GUI, and load-check scripts cover the implemented lifecycle.
- [ ] Record human compression/release, occlusion recovery, long-run performance,
  resource use, and volume change.

See [PLASTICITY.md](PLASTICITY.md). Manual depth and soft-body deformation do not
establish calibrated contact or volume conservation.
