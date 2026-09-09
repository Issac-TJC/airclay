"""Mirrored camera input and temporal assignment of MediaPipe detections."""
import itertools
import time

import numpy as np


class HandMatcher:
    def __init__(self, smoothing=0.45):
        self.previous = {}
        self.smoothing = smoothing

    def update(self, detections, t):
        # Handedness is a soft prior; wrist continuity dominates during crossings.
        sides = ("Left", "Right")
        best, cost_best = None, float("inf")
        for assignment in itertools.permutations(sides, len(detections)):
            cost = 0
            for h, side in zip(detections, assignment):
                cost += 0 if h["side"] == side else 0.20
                old = self.previous.get(side)
                if old and t - old[0] < 300:
                    cost += 2 * np.linalg.norm(np.array(h["image"])[0, :2] - np.array(old[1]["image"])[0, :2])
            if cost < cost_best:
                best, cost_best = assignment, cost
        result = {}
        for h, side in zip(detections, best or []):
            h = dict(h)
            old = self.previous.get(side)
            if old and t - old[0] < 150:
                # Don't smooth across long gaps or blend different hands.
                for key in ("image", "world"):
                    h[key] = (self.smoothing * np.array(h[key]) + (1 - self.smoothing) * np.array(old[1][key])).tolist()
            h["valid"] = True
            result[side] = h
            self.previous[side] = (t, h)
        return result


class Camera:
    def __init__(self, cfg, model_path):
        import cv2
        import mediapipe as mp
        self.cv2, self.mp, self.cfg = cv2, mp, cfg
        self.cap = cv2.VideoCapture(cfg["camera"])
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError("Cannot open camera. Grant camera access to the launching Terminal/Codex app in macOS Settings.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, cfg["fps"])
        opts = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path), delegate=mp.tasks.BaseOptions.Delegate.CPU),
            running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=2,
            min_hand_detection_confidence=cfg["confidence"],
            min_hand_presence_confidence=cfg["confidence"],
            min_tracking_confidence=cfg["confidence"])
        try:
            self.detector = mp.tasks.vision.HandLandmarker.create_from_options(opts)
        except Exception:
            self.cap.release()
            raise
        self.matcher = HandMatcher(cfg["smoothing"])
        self.last_t = -1

    def read(self):
        cv2, mp = self.cv2, self.mp
        ok, bgr = self.cap.read()
        if not ok:
            raise RuntimeError("Camera stopped delivering frames")
        bgr = cv2.flip(bgr, 1)
        t = max(self.last_t + 1, int(time.monotonic() * 1000))
        self.last_t = t
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        start = time.perf_counter()
        r = self.detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), t)
        detections = []
        for image, world, handedness in zip(r.hand_landmarks, r.hand_world_landmarks, r.handedness):
            detections.append({"side": handedness[0].category_name, "score": handedness[0].score,
                               "image": [[p.x, p.y, p.z] for p in image],
                               "world": [[p.x, p.y, p.z] for p in world]})
        frame = {"timestamp_ms": t, "hands": self.matcher.update(detections, t),
                 "inference_ms": (time.perf_counter() - start) * 1000,
                 "dominant": self.cfg["dominant"]}
        return frame, bgr

    def close(self):
        self.detector.close()
        self.cap.release()


def preview(image, frame, text):
    import cv2
    height, width = image.shape[:2]
    edges = ((0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),
             (5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),
             (13,17),(0,17),(17,18),(18,19),(19,20))
    for side, hand in frame.get("hands", {}).items():
        p = [(int(v[0] * width), int(v[1] * height)) for v in hand["image"]]
        color = (255, 180, 60) if side == "Left" else (60, 210, 100)
        for a, b in edges:
            cv2.line(image, p[a], p[b], color, 2)
        for point in p:
            cv2.circle(image, point, 3, color, -1)
        cv2.putText(image, side, p[0], cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1)
    cv2.putText(image, text, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 2)
    cv2.imshow("AirClay camera (Q to stop)", image)
    return cv2.waitKey(1) & 0xff
