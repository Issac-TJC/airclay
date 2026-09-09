"""Causal 30 Hz resampling and shared offline/online features."""
from collections import deque
import numpy as np
from airclay.interaction.state import pinch_ratio

FEATURE_VERSION = 1
FEATURE_DIM = 140
STATIC_INDICES = [i for i in range(FEATURE_DIM) if i not in (65, 66, 134, 135, 139)]
LABELS = ["idle", "sculpt", "orbit", "resize"]


class Resampler:
    def __init__(self, fps=30, max_gap_ms=150):
        self.period = 1000 / fps
        self.max_gap = max_gap_ms
        self.next_t = None
        self.previous = None

    def push(self, frame):
        t = frame["timestamp_ms"]
        if self.previous and t <= self.previous["timestamp_ms"]:
            raise ValueError("Frame timestamps must strictly increase")
        if self.next_t is None:
            self.next_t = float(t)
        output = []
        while self.next_t <= t + 1e-6:
            source = frame if abs(self.next_t - t) < 1e-6 else self.previous
            valid = source is not None and self.next_t - source["timestamp_ms"] <= self.max_gap
            output.append({"timestamp_ms": self.next_t,
                           "hands": source.get("hands", {}) if valid else {},
                           "dominant": frame.get("dominant", "Right")})
            self.next_t += self.period
        self.previous = frame
        return output


class Features:
    def __init__(self):
        self.previous = None
        self.previous_t = None
        self.previous_pair = None

    def step(self, frame):
        d = frame.get("dominant", "Right")
        sides = [d, "Left" if d == "Right" else "Right"]
        parts, wrists = [], []
        t = frame["timestamp_ms"]
        dt = (t - self.previous_t) / 1000 if self.previous_t is not None else 0
        for slot, side in enumerate(sides):
            h = frame.get("hands", {}).get(side)
            if not h or not h.get("valid", False):
                parts.extend([0.] * 69)
                wrists.append(None)
                continue
            image = np.asarray(h["image"], dtype=np.float32)
            world = np.asarray(h.get("world", h["image"]), dtype=np.float32)
            if image.shape != (21, 3) or world.shape != (21, 3) or not np.isfinite(image).all() or not np.isfinite(world).all():
                raise ValueError("Landmarks must be finite 21x3 arrays")
            local = (world - world[0]) / max(float(np.linalg.norm(world[9] - world[0])), 1e-5)
            # Canonicalize left/right chirality; retain absolute image wrist motion.
            if side == "Left":
                local[:, 0] *= -1
            wrist = image[0, :2]
            velocity = np.zeros(2)
            if self.previous and self.previous[slot] is not None and 0 < dt <= .15:
                velocity = np.clip((wrist - self.previous[slot]) / dt, -5, 5)
            parts.extend(np.clip(local, -10, 10).ravel())
            parts.extend(wrist)
            parts.extend(velocity)
            parts.extend([min(pinch_ratio(h), 10), 1.])
            wrists.append(wrist.copy())
        pair = float(np.linalg.norm(wrists[0] - wrists[1])) if all(w is not None for w in wrists) else None
        speed = 0 if pair is None or self.previous_pair is None or not 0 < dt <= .15 else np.clip((pair - self.previous_pair) / dt, -5, 5)
        parts.extend([pair or 0., speed])
        self.previous, self.previous_t, self.previous_pair = wrists, t, pair
        return np.array(parts, dtype=np.float32)


def preprocess(frames, fps=30):
    resampler, features = Resampler(fps), Features()
    timed, vectors = [], []
    for frame in frames:
        for sample in resampler.push(frame):
            timed.append(sample)
            vectors.append(features.step(sample))
    return timed, np.asarray(vectors, dtype=np.float32)
