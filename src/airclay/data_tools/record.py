import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from airclay.config import ROOT


def record(args, cfg):
    from .guided import RecordingCancelled, RoundSchedule, record_guided
    from .recording_guide import show_recording_guide
    if not all(re.fullmatch(r"[A-Za-z0-9_-]+", v) for v in (args.subject, args.session)):
        raise ValueError("Subject/session identifiers must contain only letters, numbers, _ and -")
    if args.guided:
        RoundSchedule(1, args.repetitions, getattr(args, "prepare_seconds", 5))
    folder = Path(args.output or ROOT / "data") / f"{args.subject}_{args.session}"
    if folder.exists():
        raise FileExistsError(f"Recording already exists: {folder}")
    if not show_recording_guide(args, cfg):
        print("Recording cancelled before starting; nothing saved.")
        return
    # Keep unfinished sessions out of the dataset and make explicit Q cancellation
    # safe: only this invocation's uniquely named staging directory is removed.
    staging_root = folder.parent / ".inprogress"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{folder.name}-", dir=staging_root))
    metadata = {"version": 1, "subject": args.subject, "session": args.session,
                "dominant": cfg["dominant"], "fps": cfg["fps"], "synthetic": False,
                "mirrored": False, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if args.guided:
        metadata.update(guided=True, repetitions=args.repetitions,
                        prepare_seconds=getattr(args, "prepare_seconds", 5),
                        timeline="accepted_takes")
    (staging / "metadata.json").write_text(json.dumps(metadata, indent=2))
    try:
        n = record_guided(args, cfg, staging) if args.guided else _record_free(args, cfg, staging)
        # Reserve a new destination before publishing. Existing recordings are
        # never replaced, even if one was created while this camera was running.
        folder.mkdir()
        try:
            staging.replace(folder)
        except OSError:
            try:
                folder.rmdir()  # Only removes the empty directory we just reserved.
            except OSError:
                pass
            raise
    except RecordingCancelled:
        shutil.rmtree(staging)
        print("Recording discarded; nothing saved. Run the command again to start from round 1.")
        return
    except BaseException:
        print(f"Recording was not finalized. Recovery files are preserved at: {staging}")
        raise
    print(f"Recorded {n} frames: {folder}\nReview with: airclay annotate '{folder}'")


def _record_free(args, cfg, folder):
    from airclay.tracking.camera import Camera, preview
    from .guided import RecordingCancelled
    import cv2
    camera, video, sender, pipeline = None, None, None, None
    segments, last_label, start, elapsed, n = [], "idle", None, 0., 0
    total = args.seconds
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
                prompt = f"{elapsed/1000:.1f}s | rough prompt: {label}"
                if elapsed < 3000:
                    prompt = f"Get ready: {max(1,3-int(elapsed/1000))} | open hands"
                key = preview(image, frame, prompt, controls="S  Save & finish    Q  Discard & exit")
                if key in (ord("q"), ord("Q"), 27):
                    raise RecordingCancelled
                if key in (ord("s"), ord("S")) or total and elapsed >= total*1000:
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
    return n
