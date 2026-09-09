"""Explicit synthetic fixtures: NEVER evidence of recognition accuracy."""
import json
import math
import time
from pathlib import Path
import numpy as np


def hand(x, y, closed=False, side="Right"):
    # Stylized hand skeleton with a stable wrist->middle-MCP scale of 0.10.
    p = np.array([[0, .13, 0], [-.06,.08,0], [-.08,.04,0], [-.08,0,0], [-.08,-.04,0],
                  [-.04,.035,0],[-.04,-.02,0],[-.04,-.065,0],[-.04,-.105,0],
                  [0,.03,0],[0,-.035,0],[0,-.085,0],[0,-.13,0],
                  [.04,.04,0],[.045,-.02,0],[.045,-.065,0],[.045,-.10,0],
                  [.075,.06,0],[.085,.01,0],[.09,-.03,0],[.095,-.065,0]], dtype=float)
    if closed:
        p[4] = p[8] + [.015, .003, 0]
    else:
        p[4] = p[8] + [-.08, .04, 0]
    if side == "Left":
        p[:,0] *= -1
    p[:,:2] += np.array([x,y]) - p[8,:2]
    world = (p - p[0]) * .7
    return {"valid": True, "side": side, "score": 1., "image": p.tolist(), "world": world.tolist()}


def demo_frames(fps=30, repetitions=1, jitter=0, seed=42):
    rng = np.random.default_rng(seed)
    # Neutral -> first ear -> neutral -> second ear -> orbit -> resize -> neutral.
    steps = [("idle", 1.2), ("sculpt", 2.2), ("idle", .8), ("sculpt", 2.2),
             ("idle", .8), ("orbit", 2.), ("idle", .8), ("resize", 2.), ("idle", 1.)]
    frames, annotations, t, sculpt = [], [], 0., 0
    for _ in range(repetitions):
        for label, duration in steps:
            begin = t
            if label == "sculpt":
                sculpt += 1
            for i in range(round(duration * fps)):
                u = max(0, i/fps-.35) / max(.01, duration-.35)
                dx = .565 if sculpt % 2 else .435
                right = (dx, .23 - .16*u) if label == "sculpt" else (.60,.5)
                left = (.35 + .10*u,.52) if label == "orbit" else (.35,.5)
                if label == "resize":
                    right, left = (.60+.055*u,.5), (.40-.055*u,.5)
                noise = rng.normal(0, jitter, (2,2))
                hands = {"Right": hand(*(np.array(right)+noise[0]), label in ("sculpt","resize")),
                         "Left": hand(*(np.array(left)+noise[1]), label in ("orbit","resize"), "Left")}
                frames.append({"timestamp_ms": t, "hands": hands, "dominant": "Right"})
                t += 1000/fps
            annotations.append({"start_ms": begin, "end_ms": t, "label": label})
    return frames, annotations


def make_fixtures(root):
    root = Path(root)
    for i in range(3):
        path = root / f"synthetic_{i}_session_1"
        path.mkdir(parents=True, exist_ok=True)
        frames, annotations = demo_frames(repetitions=2, jitter=.0005, seed=42+i)
        (path / "metadata.json").write_text(json.dumps({"version": 1, "subject": f"synthetic_{i}", "session": "1", "dominant": "Right", "synthetic": True, "fps": 30}))
        (path / "frames.jsonl").write_text("\n".join(json.dumps(f) for f in frames)+"\n")
        (path / "annotations.json").write_text(json.dumps({"verified": True, "verification_note": "Synthetic plumbing fixture only", "segments": annotations}, indent=2))


def simulate(args, cfg):
    from airclay.interaction.protocol import Sender
    from airclay.interaction.runner import Pipeline
    frames, _ = demo_frames(cfg["fps"], args.repetitions)
    sender, pipeline = Sender(cfg), Pipeline(cfg)
    start = time.monotonic()
    try:
        for frame in frames:
            delay = start + frame["timestamp_ms"]/1000 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            frame = {**frame, "timestamp_ms": start*1000+frame["timestamp_ms"]}
            for sample, state in pipeline.step(frame):
                sender.send(sample, state)
    finally:
        sender.close()
    print("Synthetic interaction sent. This does not test camera recognition.")
