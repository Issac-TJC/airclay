import argparse
import importlib.metadata
import json
import socket
import sys
import time
from pathlib import Path
from .config import ROOT, BLENDER, config


def main():
    parser = argparse.ArgumentParser(prog="airclay", description="Two-hand Blender sculpting and intent learning")
    parser.add_argument("--config", help="JSON config overrides")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    for name in ("track", "replay"):
        p = sub.add_parser(name)
        p.add_argument("--backend", choices=["rules","mlp","gru"], default="rules")
        p.add_argument("--checkpoint")
        p.add_argument("--no-preview", action="store_true")
        if name == "track":
            p.add_argument("--seconds", type=float, default=0)
            p.add_argument("--camera", type=int)
            p.add_argument("--output")
        else:
            p.add_argument("recording")
            p.add_argument("--speed", type=float, default=1)
    p = sub.add_parser("simulate")
    p.add_argument("--repetitions", type=int, default=1)
    p = sub.add_parser("record")
    p.add_argument("--subject", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--output")
    p.add_argument("--seconds", type=float, default=0)
    p.add_argument("--guided", action="store_true")
    p.add_argument("--repetitions", type=int, default=20)
    p.add_argument("--video", action="store_true", help="Also save optional reference video locally")
    p.add_argument("--interact", action="store_true", help="Drive Blender with this same camera stream while recording")
    p = sub.add_parser("annotate")
    p.add_argument("recording")
    p = sub.add_parser("split")
    p.add_argument("data_root")
    p.add_argument("--output", default="data/split.json")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--allow-small", action="store_true")
    p = sub.add_parser("train")
    p.add_argument("--model", choices=["mlp","gru"], required=True)
    p.add_argument("--split", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--epochs", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--device", choices=["cpu","mps"])
    p.add_argument("--allow-synthetic", action="store_true")
    p = sub.add_parser("evaluate")
    p.add_argument("--backend", choices=["rules","mlp","gru"], required=True)
    p.add_argument("--checkpoint")
    p.add_argument("--split", required=True)
    p.add_argument("--partition", choices=["val","test"], default="test")
    p.add_argument("--output", required=True)
    p.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args()
    try:
        cfg = config(args.config)
        if args.command == "doctor":
            doctor(cfg)
        elif args.command == "track":
            from .interaction.runner import track
            if args.camera is not None:
                cfg["camera"] = args.camera
            track(args,cfg)
        elif args.command == "simulate":
            from .data_tools.synthetic import simulate
            simulate(args,cfg)
        elif args.command == "record":
            from .data_tools.record import record
            record(args,cfg)
        elif args.command == "annotate":
            from .data_tools.annotate import annotate
            annotate(args)
        elif args.command == "split":
            from .data_tools.dataset import create_split
            print(json.dumps(create_split(args.data_root,args.output,args.seed,args.allow_small),indent=2))
        elif args.command == "train":
            from .learning.train import train
            train(args)
        elif args.command == "evaluate":
            from .learning.evaluate import evaluate
            evaluate(args)
        elif args.command == "replay":
            replay(args,cfg)
    except KeyboardInterrupt:
        print("Stopped")
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"AirClay: {exc}\n")


def doctor(cfg):
    versions = {}
    for pkg in ("mediapipe","opencv-contrib-python","numpy","torch","scikit-learn"):
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "MISSING"
    sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        sock.bind((cfg["host"],cfg["port"]))
        port = "free (receiver not running)"
    except OSError as exc:
        import errno
        port = "in use (expected if Blender receiver is running)" if exc.errno == errno.EADDRINUSE else f"unavailable: {exc}"
    finally:
        sock.close()
    print(json.dumps({"python":sys.version.split()[0], "executable":sys.executable,
                      "dependencies":versions,"blender":str(BLENDER),"blender_exists":BLENDER.exists(),
                      "model_exists":(ROOT/cfg["model_path"]).is_file(),"udp_port":port,
                      "camera":"not opened by doctor; test with track"},indent=2))


def replay(args,cfg):
    from .data_tools.dataset import read_recording
    from .interaction.runner import Pipeline
    from .interaction.protocol import Sender
    if args.speed <= 0:
        raise ValueError("Replay speed must be positive")
    meta,frames,_ = read_recording(args.recording)
    cfg["dominant"] = meta.get("dominant","Right")
    pipeline,sender = Pipeline(cfg,args.backend,args.checkpoint),Sender(cfg)
    start,base = time.monotonic(),frames[0]["timestamp_ms"]
    try:
        for frame in frames:
            delay = start+(frame["timestamp_ms"]-base)/1000/args.speed-time.monotonic()
            if delay>0:
                time.sleep(delay)
            # Preserve source times through recognition; only transport gets live time.
            for sample,state in pipeline.step(frame):
                sender.send({**sample,"timestamp_ms":time.monotonic()*1000},state)
            if not args.no_preview:
                import numpy as np
                from .tracking.camera import preview
                canvas=np.full((480,640,3),25,dtype=np.uint8)
                if preview(canvas,frame,f"Replay | {pipeline.controller.mode} | Q: stop") in (ord("q"),27):
                    break
    finally:
        sender.close()
        if not args.no_preview:
            import cv2
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
