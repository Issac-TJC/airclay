# UDP v2 preview protocol

`configs/hover.json` selects v2 `hover2d`; `configs/hands.json` selects v2
`hand_preview`. The default configuration remains v1. Version or profile changes
require a fresh session. Neither v2 profile carries intent or operation commands.
The receiver's separate plasticity switch can use hand-preview points for its
local experiment; see [PLASTICITY.md](PLASTICITY.md).

## Common envelope

Packets contain exactly these fields, plus `local_world_space` for `hand_preview`:

| Field | Value |
|---|---|
| `version` | Integer `2` |
| `profile` | `hover2d` or `hand_preview` |
| `session` | String, at most 100 characters |
| `seq` | Non-negative, increasing integer |
| `timestamp_ms`, `sent_ms` | Finite local monotonic milliseconds |
| `dominant` | `Left` or `Right`; control role only |
| `coordinate_space` | `camera_image_normalized` or legacy `mirrored_image_normalized` |
| `depth_available` | `false` |
| `hands` | Exactly `Left` and `Right` slots |

New camera frames use `mirrored=false` and `camera_image_normalized`. Legacy frames
without a flag use `mirrored_image_normalized`. The receiver does not reflect x
again. Image coordinates start at the top left; viewport WINDOW-region pixels are
`(x * region.width, (1-y) * region.height)`.

Left/Right denote physical hand slots, independent of screen position and dominant
role. Left markers are blue and Right markers orange. Check anatomical identity
with the user before collection; packet validation cannot establish correct tracking.

## hover2d hands

Each hand contains `valid: bool` and `fingertips`, a list of up to five entries:

```json
{
  "finger_id": "index",
  "xy": [0.45, 0.52],
  "valid": true,
  "xyz": null,
  "depth_confidence": null
}
```

The fixed IDs map to MediaPipe landmarks `thumb=4`, `index=8`, `middle=12`,
`ring=16`, and `pinky=20`; display labels are T/I/M/R/P. Order is arbitrary, but
unknown or duplicate IDs are invalid. A valid fingertip requires a valid hand and
two finite coordinates in `[0,1]`. Invalid tips may use `xy:null`. Both depth fields
must be null; handedness scores are not depth or per-joint confidence.

The sender emits all ten slots. Missing, non-finite, or out-of-frame tips become
invalid with null coordinates, rather than being clamped to the image edge.
The receiver accepts omitted tips and hides them: every packet is a full snapshot.
Malformed coordinates, duplicate IDs, extra fields, or unsupported profiles reject
the entire packet.

Blender ray-casts each tip against the target mesh. It accepts only the first hit
with a front-facing normal; it does not search behind a rejected face. Each marker
stores a local point and face ID and is reprojected when the view changes. Dashed
circles indicate hover candidates, not contact anchors. Marker radius scales with
the target bounds and view distance, with screen-size limits. **Show all fingertips**
restricts display to index fingers when off; **Show hover** hides all markers.

## hand_preview hands

The envelope adds `local_world_space: "mediapipe_hand_centered_m"`. Each hand
contains exactly `valid`, `image` (21 × 2), and `local_world` (21 × 3). Fingertips
are derived from these arrays rather than repeated in the packet.

Valid arrays contain finite numbers. Image components must have absolute value at
most 4, allowing temporary off-screen joints; local-world components must have
absolute value at most 2 meters. These are input bounds, not accuracy guarantees.
An invalid hand must set both arrays to null. Coordinates are rounded to six decimal
places. Display mapping and models are described in [HAND_PREVIEW.md](HAND_PREVIEW.md).

## Transport and lifecycle

Transport is localhost-only (`127.0.0.1`) with compact JSON and a 4096-byte payload
limit. The receiver reads one extra byte to detect oversized packets. This limit
is for local loopback, not a remote-network MTU guarantee. The hover example is
about 1.3 KB; both profiles have bounded-size test cases.

The receiver rejects duplicate/out-of-order sequences, retired sessions, invalid
timestamps, future send times, and packets at least 300 ms old. A session cannot
change version or profile. After 300 ms without a valid packet, markers and hands
are hidden; recovery uses a new full snapshot. Settings replies carry the dominant
hand. A transition from v1 to a new preview session rolls back any unfinished v1
operation. Plain preview creates no v1 undo entries.

## Existing checks

`tests/test_hover.py`, `tests/test_hand_preview.py`, and the corresponding Blender
GUI scripts cover packet validation, identity, projection, visibility, recovery,
and preservation of the target during plain preview. GUI scripts use ports 8767
(hover) and 8768 (hand preview) and write JSON results under `runs/`. A GUI result
requires `passed:true`; process exit alone is insufficient. See
[VALIDATION.md](VALIDATION.md) for historical evidence and outstanding human checks.
