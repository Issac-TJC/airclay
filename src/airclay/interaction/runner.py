import json
import time
from pathlib import Path
from airclay.config import ROOT
from .state import Controller
from .protocol import Sender
from airclay.learning.features import Resampler


class Pipeline:
    def __init__(self, cfg, backend="rules", checkpoint=None):
        self.cfg, self.backend, self.checkpoint = cfg, backend, checkpoint
        self.reset()

    def reset(self):
        self.controller = Controller(self.cfg)
        self.predictor = None
        if self.backend != "rules":
            from airclay.learning.inference import Predictor
            self.predictor = Predictor(self.checkpoint, self.backend)
        self.resampler = Resampler(self.predictor.cfg["fps"] if self.predictor else self.cfg["fps"])

    def step(self, frame):
        result = []
        for sample in self.resampler.push(frame):
            intent = self.predictor.step(sample) if self.predictor else None
            result.append((sample, self.controller.step(sample, intent)))
        return result


def track(args, cfg):
    from airclay.tracking.camera import Camera, preview
    import cv2
    pipeline = Pipeline(cfg, args.backend, args.checkpoint)
    sender = Sender(cfg)
    camera = None
    log = []
    start = time.monotonic()
    try:
        camera = Camera(cfg, ROOT / cfg["model_path"])
        while not args.seconds or time.monotonic() - start < args.seconds:
            frame, image = camera.read()
            dominant = sender.controls()
            if dominant and dominant != cfg["dominant"]:
                cfg["dominant"] = dominant
                pipeline.reset()
                # A new session rolls back an in-flight operation in Blender.
                sender.close()
                sender = Sender(cfg)
            frame["dominant"] = cfg["dominant"]
            before = time.perf_counter()
            states = pipeline.step(frame)
            for sample, state in states:
                sender.send(sample, state)
            mode = pipeline.controller.mode
            log.append({"timestamp_ms": frame["timestamp_ms"], "inference_ms": frame["inference_ms"],
                        "classifier_ms": (time.perf_counter()-before)*1000,
                        "hands": len(frame["hands"]), "mode": mode})
            if not args.no_preview and preview(image, frame, f"{args.backend} | {mode} | sculpt: {cfg['dominant']}") in (ord("q"), 27):
                break
    finally:
        # Closing the sender causes the receiver's timeout rollback.
        if camera:
            camera.close()
        sender.close()
        cv2.destroyAllWindows()
        output = Path(args.output or ROOT / "runs/track_latency.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(log, indent=2))
        print(f"Tracker stopped; {len(log)} frames, timing log: {output}")
