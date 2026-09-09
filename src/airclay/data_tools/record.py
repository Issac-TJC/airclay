import json
import re
import time
from pathlib import Path
from airclay.config import ROOT


def record(args, cfg):
    from airclay.tracking.camera import Camera, preview
    import cv2
    if not all(re.fullmatch(r"[A-Za-z0-9_-]+", v) for v in (args.subject, args.session)):
        raise ValueError("Subject/session identifiers must contain only letters, numbers, _ and -")
    folder = Path(args.output or ROOT / "data") / f"{args.subject}_{args.session}"
    folder.mkdir(parents=True, exist_ok=False)
    metadata = {"version": 1, "subject": args.subject, "session": args.session,
                "dominant": cfg["dominant"], "fps": cfg["fps"], "synthetic": False,
                "mirrored": True, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2))
    camera, video, sender, pipeline = None, None, None, None
    segments, last_label, start, elapsed, n = [], "idle", None, 0., 0
    total = 3 + args.repetitions*3*6 + 120 if args.guided else args.seconds
    try:
        if args.interact:
            from airclay.interaction.protocol import Sender
            from airclay.interaction.runner import Pipeline
            sender, pipeline = Sender(cfg), Pipeline(cfg)
        camera = Camera(cfg, ROOT / cfg["model_path"])
        with (folder / "frames.jsonl").open("w") as out:
            while True:
                frame, image = camera.read()
                if pipeline:
                    for sample, state in pipeline.step(frame):
                        sender.send(sample, state)
                start = frame["timestamp_ms"] if start is None else start
                elapsed = frame["timestamp_ms"] - start
                # Resampler retains the live frame. Never mutate its monotonic clock.
                stored_frame = {**frame, "timestamp_ms": elapsed}
                out.write(json.dumps(stored_frame)+"\n")
                out.flush()
                n += 1
                label = "idle"
                if args.guided and 3000 <= elapsed < 3000 + args.repetitions*3*6000:
                    block = int((elapsed-3000)//6000)
                    if (elapsed-3000)%6000 < 4000:
                        label = ("sculpt", "orbit", "resize")[block % 3]
                if n == 1 or label != last_label:
                    if segments:
                        segments[-1]["end_ms"] = elapsed
                    segments.append({"start_ms": elapsed, "end_ms": elapsed, "label": label})
                    last_label = label
                if args.video:
                    if video is None:
                        h,w = image.shape[:2]
                        video = cv2.VideoWriter(str(folder / "reference.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), cfg["fps"], (w,h))
                        if not video.isOpened():
                            raise RuntimeError("Cannot create reference video")
                    video.write(image)
                prompt = f"{elapsed/1000:.1f}s | rough prompt: {label} | Q: finish"
                if elapsed < 3000:
                    prompt = f"Get ready: {max(1,3-int(elapsed/1000))} | open hands"
                key = preview(image, frame, prompt)
                if key in (ord("q"),27) or total and elapsed >= total*1000:
                    break
    finally:
        if segments:
            segments[-1]["end_ms"] = elapsed + 1000/cfg["fps"]
        (folder / "annotations.json").write_text(json.dumps({"verified": False, "segments": segments}, indent=2))
        if camera:
            camera.close()
        if video:
            video.release()
        if sender:
            sender.close()
        cv2.destroyAllWindows()
    print(f"Recorded {n} frames: {folder}\nReview with: airclay annotate '{folder}'")
