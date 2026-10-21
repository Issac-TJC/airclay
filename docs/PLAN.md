# AirClay implementation

## Scope

The implemented v1 baseline has four exclusive intents: idle, sculpt, orbit, and
resize. Sculpt moves a local surface patch in the view plane, orbit rotates the
view, and resize changes brush radius. Public-data pretraining, few-shot adaptation,
calibrated depth, and concurrent object manipulation remain planned work. See the
[roadmap](IMPLEMENTATION_CHECKLIST.md) for those milestones.

UDP v2 provides `hover2d` and `hand_preview`. Both bypass the intent model and
controller. Hand preview also supports a separate, default-off
[plasticity experiment](PLASTICITY.md) using manual depth.

## Data flow

1. OpenCV reads the original camera image. MediaPipe Tasks runs in VIDEO mode,
   returning up to two sets of 21 image and hand-local world landmarks.
2. `HandMatcher` assigns Left/Right slots using detector handedness and wrist
   continuity. The default live path applies EMA with alpha 0.45 when the previous
   observation is less than 150 ms old. `record_raw.json` sets alpha to 1.0.
3. A causal resampler produces 30 Hz samples from the most recent observation.
   Observations older than 150 ms become missing. It never interpolates from future
   frames. Resampling, feature velocities, and learned windows restart at take boundaries.
4. Rules, MLP, or GRU propose one intent to the shared controller. Learned inference
   uses argmax logits; probability smoothing and calibrated rejection are absent.
5. Full-state packets go to `127.0.0.1:8765`. Blender receives on its main-thread
   modal timer, processing at most 64 datagrams per tick.
6. Blender applies view, brush, or mesh updates and stores committed operations in
   its AirClay undo history.

The program does not mirror capture or swap detector labels. Left/Right slots are
intended to identify physical hands and must be checked during collection. Temporal
matching can still fail during crossings. MediaPipe world landmarks describe each
hand locally; they do not locate both hands in a shared camera coordinate system.

## Controller and transport

A neutral observation with both hands open arms the controller. Pinch uses the 2D
thumb-tip/index-tip distance divided by wrist/middle-MCP distance, closing below
0.30 and opening above 0.45. The controller waits 200 ms before entering an active
mode, allowing a second pinch to request resize. The chosen mode stays locked.
Rule release commits immediately; learned release requires 100 ms of idle output.
A missing required hand pauses motion and cancels the operation after 300 ms.

V1 packets contain `version`, `session`, `seq`, `timestamp_ms`, `sent_ms`,
`operation_id`, `mode`, `paused`, `outcome`, `dominant`, and `hands`. Each hand carries
`valid` and a normalized index-finger `pointer`. Idle packets repeat `commit` or
`cancel` so that losing one terminal packet does not leave an operation active.

Sequences must increase within a session. A new session rolls back an unfinished
v1 operation and must send idle before starting another. An unexplained operation-ID
change also rolls back the old operation. The receiver rejects stale/future send
times, retired sessions, and duplicate or out-of-order packets; 300 ms without a
valid packet triggers rollback. Version/profile changes require a new session.
The receiver returns dominant-hand settings. Live tracking resets its pipeline and
opens a new session when that setting changes.

See [PROTOCOL_V2.md](PROTOCOL_V2.md) for preview packets and coordinate limits.

## Geometry

The demo is a unit icosphere with 10,242 vertices. Other Object Mode meshes can be
selected, but the sphere is the baseline test target.

A viewport ray selects a surface face. Dijkstra distances along mesh edges,
measured in world space and seeded at the hit face, define the affected region.
For distance `d < R`, the weight is `1 - 3(d/R)^2 + 2(d/R)^3`; it is zero outside
radius `R`. Disconnected regions receive no weight.

Sculpt freezes the initial view, brush radius, and drag plane. Each update applies
weighted displacement to the onset snapshot, capped at 0.5 world units, then
converted to mesh-local coordinates. Orbit rotates the view around the object's
origin. Resize uses the ratio of current to initial 2D index-finger separation and
clamps brush radius to 0.08–0.60. History retains 30 committed operations.

## Features and models

Hands are ordered dominant first. Each contributes 63 wrist-centered, palm-scale
normalized local coordinates, two image wrist coordinates, two wrist velocities,
a 2D pinch ratio, and a validity mask. Two-hand wrist distance and its velocity
bring the total to 140 features. Left local x is reflected to normalize chirality;
absolute image wrist positions are retained.

| Backend | Input and architecture |
|---|---|
| Rules | Pinch hysteresis and hand roles |
| MLP | Last frame's 135 non-velocity features; 128-unit ReLU layer, dropout 0.2, four logits |
| GRU | 24 × 140 input; two unidirectional 128-unit layers, dropout 0.2, four-logit head |

Both learned backends return idle until the 24-frame buffer is full. Training uses
AdamW, learning rate 0.001, batch size 64, gradient clipping at 1, at most 50 epochs,
and patience 8. Training window stride is 3; validation stride is 1. Class weights
come from training labels. The best validation Macro-F1 checkpoint records model
configuration, feature version, feature dimension, and label order.

Offline readers preserve stored coordinates. They do not reapply the camera's EMA;
raw recordings therefore need an agreed preprocessing step for filter comparisons.
