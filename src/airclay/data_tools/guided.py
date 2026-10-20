"""Round-based recording with explicit acceptance and bounded disk buffering."""
from dataclasses import dataclass
import json
import math


class RecordingCancelled(Exception):
    """The user explicitly chose to discard the current recording."""


@dataclass(frozen=True)
class Cue:
    label: str | None
    phase: str
    text: str
    controls: str = "Q  Discard & exit"


class RoundSchedule:
    actions = ("sculpt", "orbit", "resize")
    action_ms = 4000
    release_ms = 2000
    natural_ms = 120000

    def __init__(self, number, repetitions, prepare_seconds=5, attempt=1, dominant="Right"):
        if repetitions < 1:
            raise ValueError("repetitions must be at least 1")
        if not math.isfinite(prepare_seconds) or prepare_seconds <= 0:
            raise ValueError("prepare-seconds must be a positive finite number")
        self.number, self.repetitions, self.attempt = number, repetitions, attempt
        self.prepare_ms = prepare_seconds * 1000
        self.natural = number > repetitions
        self.duration_ms = self.prepare_ms + (self.natural_ms if self.natural else 3 * (self.action_ms + self.release_ms))
        other = "Left" if dominant == "Right" else "Right"
        self.active_hands = {"sculpt": dominant, "orbit": other, "resize": "Both"}

    def cue(self, elapsed):
        title = "Natural movement" if self.natural else f"Round {self.number}/{self.repetitions}"
        if elapsed >= self.duration_ms:
            if self.natural:
                return Cue(None, "done", "Recording complete")
            next_name = "NATURAL MOVEMENT" if self.number == self.repetitions else f"Round {self.number + 1}/{self.repetitions}"
            return Cue(None, "review", f"{title} | PAUSED\nNext: {next_name}",
                       "R  Retry    N / Space  Next\nQ  Discard & exit")
        if elapsed < self.prepare_ms:
            next_name = "NATURAL MOVEMENT" if self.natural else "SCULPT"
            return Cue("idle", "prepare", f"{title} | GET READY\nNext: {next_name} in {(self.prepare_ms - elapsed) / 1000:.1f}s")
        if self.natural:
            return Cue("idle", "natural", f"NATURAL MOVEMENT | {(self.duration_ms - elapsed) / 1000:.1f}s left")
        block_ms = self.action_ms + self.release_ms
        index = min(2, int((elapsed - self.prepare_ms) // block_ms))
        within = elapsed - self.prepare_ms - index * block_ms
        label = self.actions[index]
        next_name = self.actions[index + 1].upper() if index < 2 else "PAUSE"
        next_in = (block_ms - within) / 1000
        if within < self.action_ms:
            return Cue(label, "action", f"{title} | {label.upper()} ({self.active_hands[label]}) | {(self.action_ms - within) / 1000:.1f}s\nNext: {next_name} in {next_in:.1f}s")
        return Cue("idle", "release", f"{title} | OPEN HANDS\nNext: {next_name} in {next_in:.1f}s")


class _Take:
    def __init__(self, folder, schedule, cfg, with_video):
        name = "natural" if schedule.natural else f"round_{schedule.number:02d}_take_{schedule.attempt:02d}"
        self.path = folder / "takes" / name
        self.path.mkdir(parents=True)
        self.schedule, self.cfg, self.with_video = schedule, cfg, with_video
        self.out = (self.path / "frames.jsonl").open("w")
        self.video = None
        self.start = None
        self.last = 0
        self.count = 0
        self.end_ms = 0
        self.segments = []
        self.closed = False

    def elapsed(self, timestamp):
        if self.start is None:
            self.start = timestamp
        return timestamp - self.start

    def write(self, frame, image, label):
        import cv2
        elapsed = self.elapsed(frame["timestamp_ms"])
        saved = {**frame, "timestamp_ms": elapsed, "capture_timestamp_ms": frame["timestamp_ms"]}
        self.out.write(json.dumps(saved) + "\n")
        self.out.flush()
        if not self.segments or label != self.segments[-1]["label"]:
            if self.segments:
                self.segments[-1]["end_ms"] = elapsed
            self.segments.append({"start_ms": elapsed, "end_ms": elapsed, "label": label})
        if self.with_video:
            if self.video is None:
                h, w = image.shape[:2]
                self.video = cv2.VideoWriter(str(self.path / "reference.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), self.cfg["fps"], (w, h))
                if not self.video.isOpened():
                    raise RuntimeError("Cannot create reference video")
            self.video.write(image)
        self.last, self.count = elapsed, self.count + 1

    def close(self):
        if self.closed:
            return
        self.out.close()
        if self.video:
            self.video.release()
        if self.segments:
            self.end_ms = min(self.last + 1000 / self.cfg["fps"], self.schedule.duration_ms)
            self.segments[-1]["end_ms"] = self.end_ms
        (self.path / "annotations.json").write_text(json.dumps({"verified": False, "segments": self.segments}, indent=2))
        self.closed = True


class _Session:
    def __init__(self, folder, cfg, with_video):
        self.folder, self.cfg, self.with_video = folder, cfg, with_video
        self.out = (folder / "frames.jsonl").open("w")
        self.video = None
        self.offset = 0
        self.count = 0
        self.segments, self.takes = [], []

    def finish_take(self, take, decision, complete):
        import cv2
        take.close()
        take_id = str(take.path.relative_to(self.folder))
        entry = {"take_id": take_id, "round": take.schedule.number,
                 "kind": "natural" if take.schedule.natural else "round",
                 "attempt": take.schedule.attempt, "decision": decision,
                 "complete": complete, "frames": take.count}
        if decision != "rejected" and take.count:
            entry.update(start_ms=self.offset, end_ms=self.offset + take.end_ms)
            # Local timestamps retain the actual cadence inside each take.
            # The capture clock is also retained; pauses/retakes are not training time.
            with (take.path / "frames.jsonl").open() as source:
                for line in source:
                    frame = json.loads(line)
                    frame["timestamp_ms"] += self.offset
                    frame["take_id"] = take_id
                    self.out.write(json.dumps(frame) + "\n")
            self.out.flush()
            if self.with_video:
                cap = cv2.VideoCapture(str(take.path / "reference.mp4"))
                decoded = 0
                try:
                    while True:
                        ok, image = cap.read()
                        if not ok:
                            break
                        if self.video is None:
                            h, w = image.shape[:2]
                            self.video = cv2.VideoWriter(str(self.folder / "reference.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), self.cfg["fps"], (w, h))
                            if not self.video.isOpened():
                                raise RuntimeError("Cannot create session reference video")
                        self.video.write(image)
                        decoded += 1
                finally:
                    cap.release()
                if decoded != take.count:
                    raise RuntimeError(f"Video/landmark count mismatch in {take_id}; source take preserved")
            self.segments.extend({**s, "start_ms": s["start_ms"] + self.offset,
                                  "end_ms": s["end_ms"] + self.offset} for s in take.segments)
            self.offset += take.end_ms
            self.count += take.count
        self.takes.append(entry)
        (take.path / "take.json").write_text(json.dumps(entry, indent=2))
        self.checkpoint()

    def checkpoint(self):
        (self.folder / "annotations.json").write_text(json.dumps({"verified": False, "segments": self.segments}, indent=2))
        (self.folder / "recording_takes.json").write_text(json.dumps(self.takes, indent=2))

    def close(self):
        self.out.close()
        if self.video:
            self.video.release()
        self.checkpoint()


def record_guided(args, cfg, folder):
    import cv2
    from airclay.config import ROOT
    from airclay.tracking.camera import Camera, preview
    from airclay.interaction.protocol import Sender
    from airclay.interaction.runner import Pipeline

    prepare = getattr(args, "prepare_seconds", 5)
    number, attempt = 1, 1
    schedule = RoundSchedule(number, args.repetitions, prepare, attempt, cfg["dominant"])
    session = _Session(folder, cfg, args.video)
    camera = sender = pipeline = take = None
    cue = None
    cancelled = False
    try:
        camera = Camera(cfg, ROOT / cfg["model_path"])
        take = _Take(folder, schedule, cfg, args.video)
        while True:
            frame, image = camera.read()
            cue = schedule.cue(take.elapsed(frame["timestamp_ms"]))
            if cue.phase == "done":
                finished, take = take, None
                session.finish_take(finished, "accepted", True)
                break
            if cue.phase == "review":
                take.close()
                if sender:
                    sender.close()
                    sender = pipeline = None
            else:
                take.write(frame, image, cue.label)
                if args.interact:
                    if sender is None:
                        sender, pipeline = Sender(cfg), Pipeline(cfg)
                    for sample, state in pipeline.step(frame):
                        sender.send(sample, state)
            key = preview(image, frame, cue.text, controls=cue.controls)
            if key in (ord("q"), ord("Q"), 27):
                cancelled = True
                raise RecordingCancelled
            if cue.phase == "review" and key in (ord("r"), ord("R"), ord("n"), ord("N"), ord(" "), 13):
                repeat = key in (ord("r"), ord("R"))
                finished, take = take, None
                session.finish_take(finished, "rejected" if repeat else "accepted", True)
                if repeat:
                    attempt += 1
                else:
                    number, attempt = number + 1, 1
                schedule = RoundSchedule(number, args.repetitions, prepare, attempt, cfg["dominant"])
                take = _Take(folder, schedule, cfg, args.video)
                cue = None
    finally:
        try:
            if take:
                if cancelled:
                    take.close()
                else:
                    complete = cue is not None and cue.phase == "review"
                    session.finish_take(take, "accepted" if complete else "interrupted", complete)
        finally:
            session.close()
            if camera:
                camera.close()
            if sender:
                sender.close()
            cv2.destroyAllWindows()
    return session.count
