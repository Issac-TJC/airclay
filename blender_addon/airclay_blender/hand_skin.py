"""Weighted skinning of Elena FF's hand onto AirClay's 21 tracked joints.

Pure NumPy math. The separately licensed mesh/texture assets are CC BY-SA 4.0;
see assets/HAND_LICENSE.txt. Source rig controls/animations are not executed.
"""
from pathlib import Path
import numpy as np

ASSETS = Path(__file__).parent / 'assets'


def unit(vector, fallback):
    length = np.linalg.norm(vector)
    return vector / length if length > 1e-8 else np.asarray(fallback, dtype=np.float64)


def palm_frame(points):
    y = unit(points[9] - points[0], (0, 1, 0))
    across = points[5] - points[17]
    x = unit(across - y * np.dot(across, y), (1, 0, 0))
    z = unit(np.cross(x, y), (0, 0, 1))
    x = unit(np.cross(y, z), (1, 0, 0))
    return np.column_stack((x, y, z))


def segment_frame(a, b, palm):
    y = unit(b - a, palm[:, 1])
    x = unit(np.cross(y, palm[:, 2]), palm[:, 0])
    z = unit(np.cross(x, y), palm[:, 2])
    return np.column_stack((x, y, z))


def aim_frame(frame, direction):
    """Parallel-transport the bind frame; no roll flip at a 90-degree curl."""
    a, b = frame[:, 1], unit(direction, frame[:, 1])
    cosine = np.clip(np.dot(a, b), -1., 1.)
    if cosine < -0.99999:
        axis = frame[:, 0]
        rotation = 2 * np.outer(axis, axis) - np.eye(3)
    else:
        x, y, z = np.cross(a, b)
        cross = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
        rotation = np.eye(3) + cross + cross @ cross / (1 + cosine)
    return rotation @ frame


class HandSkin:
    def __init__(self, path=None):
        with np.load(path or ASSETS / 'hand_mesh.npz', allow_pickle=False) as data:
            for key in ('vertices', 'triangles', 'uv', 'joints', 'weights', 'rest_points', 'rest_starts', 'segments'):
                setattr(self, key, data[key].copy())
        p = self.rest_points.astype(np.float64)
        self.palm = palm_frame(p)
        self.width = np.linalg.norm(p[5] - p[17])
        self.length = np.linalg.norm(p[9] - p[0])
        starts, frames, lengths = [p[0]], [self.palm], [self.length]
        for i, (a, b) in enumerate(self.segments[1:], 1):
            start = self.rest_starts[i].astype(np.float64)
            starts.append(start)
            frames.append(segment_frame(start, p[b], self.palm))
            lengths.append(np.linalg.norm(p[b] - start))
        self.rest_frames = np.asarray(frames)
        self.lengths = np.asarray(lengths)
        relative = self.vertices[:, None, :] - np.asarray(starts)[self.joints]
        self.local = np.einsum('nkji,nkj->nki', self.rest_frames[self.joints], relative)

    def deform(self, points, side='Right', flip_depth=False):
        p = np.asarray(points, dtype=np.float64)
        if p.shape != (21, 3) or not np.isfinite(p).all():
            raise ValueError('Hand skin needs 21 finite joint positions')
        palm = palm_frame(p)
        width = max(np.linalg.norm(p[5] - p[17]) / self.width, 1e-6)
        length = max(np.linalg.norm(p[9] - p[0]) / self.length, 1e-6)
        thickness = np.sqrt(width * length)
        # Mirrored left anatomy and front/back reflections affect thickness as
        # well as joint centers. Flipping only tracked z leaves palms reversed.
        sign = (-1 if side == 'Left' else 1) * (-1 if flip_depth else 1)
        frames = [palm * np.array([width, length, thickness * sign])]
        orientation = (palm * np.array([1, 1, sign])) @ self.palm.T
        starts = [p[0]]
        for i, (a, b) in enumerate(self.segments[1:], 1):
            # Metacarpal weights start inside the palm, not at the wrist. Move
            # those anchors with the palm to avoid a crease across its center.
            start = (p[0] + frames[0] @ self.palm.T @ (self.rest_starts[i] - self.rest_points[0])) if a == 0 else p[a]
            stretch = max(np.linalg.norm(p[b] - start) / self.lengths[i], 1e-6)
            frames.append(aim_frame(orientation @ self.rest_frames[i], p[b] - start) * np.array([thickness, stretch, thickness]))
            starts.append(start)
        positions = np.einsum('nkij,nkj->nki', np.asarray(frames)[self.joints], self.local)
        positions += np.asarray(starts)[self.joints]
        return (positions * self.weights[:, :, None]).sum(axis=1).astype(np.float32)
