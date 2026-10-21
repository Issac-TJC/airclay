# Tracked hand preview

`configs/hands.json` enables the UDP v2 `hand_preview` profile. Each hand sends
21 image joints and 21 hand-local world landmarks. Blender fits a display mesh to
these points; it does not reconstruct the user's own hand surface.

## Run and display controls

Start the receiver and one tracker in separate terminals:

```bash
bash scripts/start_blender.sh
```

```bash
.venv/bin/airclay --config configs/hands.json track --backend rules
```

Replace `track --backend rules` with `simulate` for synthetic opening, pinching,
and loss/recovery, or with `replay <recording>` for recorded landmarks. Replay uses
only the stored image and world points and does not estimate missing root depth.
Restart Blender after updating the add-on.

The **Hand model** selector offers:

| Model | Geometry per hand | Display |
|---|---|---|
| Smooth blue hand (default) | 14,499 vertices, 28,994 triangles | Blue surface, smoothed skin weights and tapered wrist |
| Realistic skin | 16,330 vertices, 28,994 triangles | Original skin weights, UVs, color and roughness textures |
| Simple joints | 876 vertices | Joint spheres, finger segments, and a palm |

Meshes are reused each frame, and styles can be changed while receiving. Smooth
hands are both blue; cursors and the legend distinguish Left (blue) and Right
(orange). The other models use those identity colors in Solid view. Material
Preview shows the realistic skin textures. The add-on leaves viewport shading
under user control.

- **Show tracked hands** controls visibility. Hiding hands also pauses an enabled
  plasticity experiment.
- **Hand display depth** offsets the display plane near the target. It is not a
  camera calibration or a measurement of wrist depth.
- **Flip hand front/back** defaults to on. It reverses wrist-relative depth and skin
  orientation while retaining image position, wrist position, identity, and pinch
  feedback. Choose the setting that matches the camera view.
- **Fingertip direction guides** toggles yellow lines in Smooth mode. They show
  direction only and do not apply force.

OPEN/PINCH/LOST reports pose. Pinch uses local 3D thumb/index-tip distance divided
by wrist/middle-MCP distance, with close/open thresholds 0.30/0.45. This differs
from the v1 controller's 2D pinch ratio and does not trigger a v1 sculpt operation.
Invalid skeletons and timeouts hide the hands and clear pinch feedback.

## Depth and lifetime

Image coordinates place the joints on a view plane. Wrist-relative local depth
adds hand articulation, scaled using the palm's size on that plane. Root depth
is uncalibrated; the preview cannot establish shared camera-space positions or
physical contact. Visual overlap with the target does not prove contact.

Generated hand objects are excluded from sculpt-target selection. They have no
collision modifiers; the optional [plasticity experiment](PLASTICITY.md) manages
separate fingertip spheres. Saving a `.blend` retains a static hand pose and embeds
realistic textures. Stopping the receiver removes the display objects and resources.
If model assets cannot be read, the display falls back to Simple joints and shows
the reason in the panel.

## Assets and fitting

The base asset is [Rigged hand by Elena FF](https://sketchfab.com/3d-models/rigged-hand-eae97cc2a742413cb5338ab942b12c1e).
Its recorded license is CC BY-SA 4.0. Attribution, source information, and hashes
are retained in [HAND_LICENSE.txt](../blender_addon/airclay_blender/assets/HAND_LICENSE.txt),
[hand_manifest.json](../blender_addon/airclay_blender/assets/hand_manifest.json), and
[smooth_manifest.json](../blender_addon/airclay_blender/assets/smooth_manifest.json).

`scripts/prepare_hand_asset.py` extracts the source mesh, skin weights, UVs, and
textures. Runtime fitting maps deform joints to tracked landmarks and mirrors the
left hand. `scripts/prepare_smooth_hand.py` welds seams, applies Taubin smoothing,
extends/tapers the wrist, and adjusts palm and skin weights. Bone orientation follows
continuous rotations from the bind pose. Extreme poses, occlusion, and poor landmarks
can still cause skin overlap; synthetic projection checks do not measure personal fit.

## Protocol and checks

The full schema is in [PROTOCOL_V2.md](PROTOCOL_V2.md). `hand_preview` uses the same
version as `hover2d` but requires its own session when switching profiles.

`test_hand_preview_gui.py` checks 42-joint projection, pinch feedback, front/back
reflection, mesh reuse, visibility, timeout recovery, and cleanup. Its `--realistic`
and `--smooth` variants cover assets, textures, style switching, and direction guides.
Outputs use `runs/hand_preview/`, `runs/realistic_hand/`, and `runs/smooth_hand/`.
See [VALIDATION.md](VALIDATION.md) for the status of saved results. Human fit,
crossings, occlusion, and long sessions still need recorded acceptance evidence.
