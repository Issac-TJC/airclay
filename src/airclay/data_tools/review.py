"""Read-only video review, synchronized to recorded frame timestamps."""
import hashlib
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .dataset import label_at, read_recording
from airclay.learning.features import LABELS


def review_groups(frames, takes):
    """Use accepted frame runs, never rejected takes or nominal video FPS."""
    descriptions = {take["take_id"]: take for take in takes if take["decision"] == "accepted"}
    groups = []
    for take_id, items in itertools.groupby(enumerate(frames), lambda item: item[1].get("take_id")):
        indices = [index for index, _ in items]
        take = descriptions.get(take_id, {})
        title = f"Round {take['round']:02d}" if take.get("kind") == "round" else "Natural movement" if take.get("kind") == "natural" else f"Part {len(groups) + 1}"
        groups.append({"start": indices[0], "stop": indices[-1] + 1, "title": title, "take_id": take_id})
    return groups


class Playback:
    def __init__(self, frames, groups):
        self.frames, self.groups = frames, groups
        self.group = self.index = 0
        self.playing = False
        self.speed = 1.0
        self.deadline = None

    def schedule(self, now):
        self.deadline = None
        if self.playing and self.index + 1 < self.groups[self.group]["stop"]:
            delta = self.frames[self.index + 1]["timestamp_ms"] - self.frames[self.index]["timestamp_ms"]
            self.deadline = now + delta / 1000 / self.speed
        else:
            self.playing = False

    def advance(self, now):
        if self.playing and self.deadline is not None and now >= self.deadline:
            self.index += 1
            self.schedule(self.deadline)

    def jump(self, group, now):
        self.group = max(0, min(len(self.groups) - 1, group))
        self.index = self.groups[self.group]["start"]
        self.playing = True
        self.schedule(now)

    def step(self, delta):
        group = self.groups[self.group]
        self.index = max(group["start"], min(group["stop"] - 1, self.index + delta))
        self.playing = False
        self.deadline = None


class ReferenceVideo:
    def __init__(self, path, count):
        import cv2
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened() or int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) != count:
            self.cap.release()
            raise ValueError(f"{path}: reference video must contain exactly {count} frames")
        self.index, self.image = -1, None

    def read(self, index):
        import cv2
        if index != self.index:
            if index != self.index + 1:
                if not self.cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                    raise RuntimeError(f"Cannot seek reference video to frame {index}")
            ok, image = self.cap.read()
            if not ok:
                raise RuntimeError(f"Cannot decode reference video frame {index}")
            self.index, self.image = index, image
        return self.image

    def close(self):
        self.cap.release()


COLORS = {"idle": (145, 145, 145), "sculpt": (105, 215, 145), "orbit": (245, 185, 100), "resize": (155, 150, 250)}
ROLES = {"idle": "", "sculpt": "dominant hand", "orbit": "other hand", "resize": "both hands"}


def render(image, path, state, annotations, message=""):
    import cv2
    # Separate bars keep fingers and the entire original image visible.
    width = 960
    height = round(image.shape[0] * width / image.shape[1])
    canvas = np.full((height + 160, width, 3), 24, dtype=np.uint8)
    canvas[64:64 + height] = cv2.resize(image, (width, height))
    frame = state.frames[state.index]
    timestamp = frame["timestamp_ms"]
    label = LABELS[label_at(timestamp, annotations)]
    group = state.groups[state.group]

    def text(value, xy, scale=.5, color=(225, 225, 225)):
        cv2.putText(canvas, value, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)

    text(f"{label.upper()}  {ROLES[label]}", (16, 28), .72, COLORS[label])
    status = "PLAYING" if state.playing else "ROUND END" if state.index == group["stop"] - 1 else "PAUSED"
    text(f"{path.name}  |  {group['title']}  |  {timestamp / 1000:.2f}s  |  {state.speed:g}x  {status}", (16, 51))
    start = state.frames[group["start"]]["timestamp_ms"]
    end = state.frames[group["stop"] - 1]["timestamp_ms"]
    duration = max(1, end - start)
    x_at = lambda t: 16 + round(928 * (t - start) / duration)
    y = height + 75
    for segment in annotations["segments"]:
        left, right = max(start, segment["start_ms"]), min(end, segment["end_ms"])
        if right > left:
            cv2.rectangle(canvas, (x_at(left), y), (x_at(right), y + 9), COLORS[segment["label"]], -1)
    cv2.line(canvas, (x_at(timestamp), y - 3), (x_at(timestamp), y + 13), (255, 255, 255), 2)
    if message:
        text(message, (16, height + 108), .46, (130, 220, 255))
    controls = ["Space play/pause  |  A/D frame  |  N/P round  |  R repeat",
                "F flag issue  |  +/- speed  |  Tab session  |  Q exit"]
    for row, value in enumerate(controls):
        tw = cv2.getTextSize(value, cv2.FONT_HERSHEY_SIMPLEX, .45, 1)[0][0]
        text(value, (width - 16 - tw, height + 131 + row * 20), .45)
    return canvas


def flag_issue(path, state, annotations, annotation_hash):
    frame = state.frames[state.index]
    flag = {"created": datetime.now(timezone.utc).isoformat(), "recording": path.name,
            "group": state.groups[state.group]["title"], "take_id": frame.get("take_id"),
            "frame_index": state.index, "timestamp_ms": frame["timestamp_ms"],
            "label": LABELS[label_at(frame["timestamp_ms"], annotations)],
            "annotations_sha256": annotation_hash, "status": "needs_review"}
    with (path / "human_review_flags.jsonl").open("a") as output:
        output.write(json.dumps(flag) + "\n")
    return flag


def review(args):
    import cv2
    paths = [Path(path) for path in args.recordings]
    window = "AirClay label review"
    session = 0
    print("Review only: annotations and verified status stay unchanged. F saves a separate issue marker.", flush=True)
    try:
        while True:
            path = paths[session]
            _, frames, annotations = read_recording(path)
            takes_path = path / "recording_takes.json"
            takes = json.loads(takes_path.read_text()) if takes_path.exists() else []
            annotation_hash = hashlib.sha256((path / "annotations.json").read_bytes()).hexdigest()
            state = Playback(frames, review_groups(frames, takes))
            video = ReferenceVideo(path / "reference.mp4", len(frames))
            message = ""
            last_drawn = None
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window, 960, 880)
            if getattr(args, "autoplay", False):
                state.jump(0, time.monotonic())
            print(f"Opened {path.name}: {len(state.groups)} parts. {'Playing.' if state.playing else 'Space starts playback.'}", flush=True)
            try:
                while True:
                    now = time.monotonic()
                    state.advance(now)
                    signature = (state.index, state.playing, state.speed, message)
                    if signature != last_drawn:
                        cv2.imshow(window, render(video.read(state.index), path, state, annotations, message))
                        last_drawn = signature
                    key = cv2.waitKey(10) & 0xff
                    if key in (ord("q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                        return
                    if key == 9:
                        session = (session + 1) % len(paths)
                        break
                    if key == ord(" "):
                        state.playing = not state.playing
                        state.schedule(time.monotonic())
                    elif key in (ord("n"), ord("p"), ord("r")):
                        delta = {ord("n"): 1, ord("p"): -1, ord("r"): 0}[key]
                        state.jump(state.group + delta, time.monotonic())
                        message = ""
                    elif key in (ord("a"), ord("d")):
                        state.step(-1 if key == ord("a") else 1)
                    elif key in (ord("-"), ord("+"), ord("=")):
                        state.speed = max(.25, min(2, state.speed * (.5 if key == ord("-") else 2)))
                        state.schedule(time.monotonic())
                    elif key == ord("f"):
                        state.step(0)
                        flag = flag_issue(path, state, annotations, annotation_hash)
                        message = f"Flag saved: {flag['group']} / {flag['label']} / {flag['timestamp_ms'] / 1000:.2f}s"
                        print(message, flush=True)
            finally:
                video.close()
    finally:
        cv2.destroyAllWindows()
