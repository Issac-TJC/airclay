"""Build the smooth reference-style hand from the licensed anatomical mesh.

Weld UV seam duplicates, smooth geometry/weights, extend and taper the wrist.
The reference variant intentionally has no skin texture. Source stays intact.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'blender_addon/airclay_blender/assets'
spec = importlib.util.spec_from_file_location('hand_skin', ASSETS.parent / 'hand_skin.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def build():
    skin = module.HandSkin()
    _, ids, inverse = np.unique(np.round(skin.vertices, 6), axis=0, return_index=True, return_inverse=True)
    vertices = skin.vertices[ids].astype(np.float64)
    triangles = inverse[skin.triangles]
    edges = np.unique(np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1), axis=0)
    a, b = np.concatenate([edges[:, 0], edges[:, 1]]), np.concatenate([edges[:, 1], edges[:, 0]])
    degree = np.bincount(a, minlength=len(vertices))[:, None]

    def average(values):
        return np.column_stack([np.bincount(a, weights=values[b, i], minlength=len(vertices)) for i in range(values.shape[1])]) / degree

    # Taubin smoothing removes grooves and seam artifacts without the shrinkage
    # of repeated one-way Laplacian smoothing. Keep the anatomical silhouette.
    for _ in range(18):
        vertices += .5 * (average(vertices) - vertices)
        vertices -= .53 * (average(vertices) - vertices)
    p = (vertices - skin.rest_points[0]) @ skin.palm
    low, high = p[:, 1].min(), .15
    w = np.clip((high - p[:, 1]) / (high - low), 0, 1)
    w = w * w * (3 - 2 * w)
    # A short tapered wrist replaces the flared, almost missing original cuff.
    p[:, 1] -= .20 * w
    p[:, 0] *= 1 - .13 * w
    p[:, 2] *= 1 - .10 * w
    vertices = p @ skin.palm.T + skin.rest_points[0]
    weights = np.zeros((len(vertices), len(skin.segments)), dtype=np.float64)
    counts = np.bincount(inverse)
    for i in range(skin.weights.shape[1]):
        np.add.at(weights, (inverse, skin.joints[:, i]), skin.weights[:, i])
    weights /= counts[:, None]
    # Treat the palm as one continuous surface. Independent metacarpal stretch
    # on a monocular skeleton otherwise folds the wrist/palm like five flaps.
    for base in (1, 5, 9, 13, 17):
        weights[:, 0] += weights[:, base]
        weights[:, base] = 0
    for _ in range(8):
        weights += .35 * (average(weights) - weights)
    # The cuff is carried by the palm, never stretched by finger weights.
    root = np.clip((.20 - p[:, 1]) / .25, 0, 1)
    root = root * root * (3 - 2 * root)
    weights *= 1 - root[:, None]
    weights[:, 0] += root
    joints = np.argsort(weights, axis=1)[:, -8:]
    weights = np.take_along_axis(weights, joints, axis=1)
    weights /= weights.sum(axis=1, keepdims=True)
    np.savez_compressed(ASSETS / 'hand_smooth.npz', vertices=vertices.astype(np.float32), triangles=triangles.astype(np.int32),
                        uv=np.zeros((len(vertices), 2), dtype=np.float32), joints=joints.astype(np.uint8), weights=weights.astype(np.float32),
                        rest_points=skin.rest_points, rest_starts=skin.rest_starts, segments=skin.segments)
    info = {'source': 'hand_mesh.npz', 'source_sha256': hashlib.sha256((ASSETS / 'hand_mesh.npz').read_bytes()).hexdigest(),
            'asset_license': 'CC-BY-SA-4.0', 'author': 'Elena FF; reference-style adaptation by AirClay',
            'changes': 'Welded UV seams; 18 Taubin smoothing pairs; tapered wrist extended by 0.20 source units; unified palm weights and smoothed eight-influence skin weights; uniform blue material.',
            'vertices': len(vertices), 'triangles': len(triangles), 'wrist_extension': .20,
            'hand_smooth_sha256': hashlib.sha256((ASSETS / 'hand_smooth.npz').read_bytes()).hexdigest()}
    (ASSETS / 'smooth_manifest.json').write_text(json.dumps(info, indent=2) + '\n')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    build()
