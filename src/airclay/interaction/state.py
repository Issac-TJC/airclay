"""Causal interaction arbitration; independent of the camera and Blender."""
import math

MODES = ("idle", "sculpt", "orbit", "resize")


def pinch_ratio(hand):
    if not hand or not hand.get("valid", True):
        return None
    p = hand["image"]
    scale = math.dist(p[0][:2], p[9][:2])
    return math.dist(p[4][:2], p[8][:2]) / max(scale, 1e-5)


class Controller:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = "idle"
        self.operation = 0
        self.closed = {"Left": False, "Right": False}
        self.armed = False  # Require a neutral observation on connect.
        self.pending_at = None
        self.release_at = None
        self.lost_at = None
        self.done = None

    def step(self, frame, intent=None):
        t = frame["timestamp_ms"]
        hands = frame.get("hands", {})
        valid = {k: bool(hands.get(k, {}).get("valid", False)) for k in self.closed}
        for side in self.closed:
            ratio = pinch_ratio(hands.get(side))
            if ratio is not None:
                if ratio < self.cfg["pinch_close"]:
                    self.closed[side] = True
                elif ratio > self.cfg["pinch_open"]:
                    self.closed[side] = False
        d = self.cfg["dominant"]
        a = "Left" if d == "Right" else "Right"
        required = {"sculpt": [d], "orbit": [a], "resize": [d, a]}
        dc, ac = valid[d] and self.closed[d], valid[a] and self.closed[a]
        neutral = all(valid.values()) and not any(self.closed.values())
        rule = "resize" if dc and ac else "sculpt" if dc else "orbit" if ac else "idle"
        desired = rule if intent is None else intent
        if desired not in MODES:
            desired = "idle"
        paused = False

        if self.mode != "idle":
            if not all(valid[s] for s in required[self.mode]):
                paused = True
                self.lost_at = t if self.lost_at is None else self.lost_at
                if t - self.lost_at >= self.cfg["loss_ms"]:
                    self._finish("cancel")
            else:
                self.lost_at = None
                # Other intentions cannot steal an active gesture.
                if intent is None:
                    released = not all(self.closed[s] for s in required[self.mode])
                else:
                    released = desired == "idle"
                if released:
                    self.release_at = t if self.release_at is None else self.release_at
                    wait = 0 if intent is None else self.cfg["intent_ms"]
                    if t - self.release_at >= wait:
                        self._finish("commit")
                else:
                    self.release_at = None
        elif not self.armed:
            if neutral:
                self.armed = True
                self.closed = {s: self.closed[s] if valid[s] else False for s in self.closed}
        elif desired == "idle" or not all(valid[s] for s in required.get(desired, [])):
            self.pending_at = None
        else:
            if self.pending_at is None:
                self.pending_at = t
            if t - self.pending_at >= self.cfg["combo_ms"]:
                self.mode = desired
                self.operation += 1
                self.pending_at = None
                self.done = None

        return {"mode": self.mode, "operation_id": self.operation,
                "paused": paused, "outcome": self.done, "rule_intent": rule}

    def _finish(self, outcome):
        # Outcome repeats on idle packets, so a lost terminal packet is harmless.
        self.done = outcome
        self.mode = "idle"
        self.armed = False
        self.pending_at = self.release_at = self.lost_at = None
