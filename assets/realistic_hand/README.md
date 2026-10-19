# Rigged hand — Elena FF

Source: https://sketchfab.com/3d-models/rigged-hand-eae97cc2a742413cb5338ab942b12c1e

Author: Elena FF (https://sketchfab.com/elenaferfor)

License: CC BY-SA 4.0 — https://creativecommons.org/licenses/by-sa/4.0/

`source.glb` was obtained from the public redistribution at
https://github.com/bizzkoot/Hand-Math/blob/main/assets/models/hand_right.glb .
The embedded glTF metadata identifies the same author, original source and license.
It is retained for reproducibility; source controls/animations are not executed.

Run `.venv/bin/python scripts/prepare_hand_asset.py` from the project root to
extract the mesh, original skin weights, UV and textures into the add-on assets.
AirClay remaps the weighted deform joints to its 21 tracked landmarks, mirrors
the left hand, and handles front/back reflection at runtime. The derived model
assets are distributed under CC BY-SA 4.0 with their attribution.

Run `.venv/bin/python scripts/prepare_smooth_hand.py` after the base extraction
to generate the reference-style blue hand. It welds seams, smooths geometry and
skin weights, extends/tapers the wrist and unifies the palm weights. See
`smooth_manifest.json` for its source and output hashes. This derived mesh is
also CC BY-SA 4.0.

See `blender_addon/airclay_blender/assets/HAND_LICENSE.txt` for the attribution and
`hand_manifest.json` in that directory for source and derived-file SHA-256 values.
