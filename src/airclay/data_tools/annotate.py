"""Offline skeleton annotation UI. Labels are manually reviewed, not rule outputs."""
import json
from pathlib import Path
import numpy as np
from .dataset import read_recording, label_at
from airclay.learning.features import LABELS


def replace_interval(segments, start, end, label):
    if end <= start:
        raise ValueError("End must follow start")
    result = []
    for s in segments:
        if s["end_ms"] <= start or s["start_ms"] >= end:
            result.append(s)
        else:
            if s["start_ms"] < start:
                result.append({**s, "end_ms": start})
            if s["end_ms"] > end:
                result.append({**s, "start_ms": end})
    result.append({"start_ms": start, "end_ms": end, "label": label})
    return sorted(result, key=lambda s: s["start_ms"])


def annotate(args):
    import cv2
    from airclay.tracking.camera import preview
    path = Path(args.recording)
    meta, frames, annotations = read_recording(path)
    index, mark_in, mark_out, playing, dirty = 0, None, None, False, False
    print("SPACE play/pause | A/D one frame | J/L 30 frames | I/O range | 0 idle,1 sculpt,2 orbit,3 resize | V verify | S save | Q quit")
    try:
        while True:
            frame = frames[index]
            canvas = np.zeros((480, 800, 3), dtype=np.uint8)
            canvas[:] = (25,25,25)
            label = LABELS[label_at(frame["timestamp_ms"], annotations)]
            text = f"{index+1}/{len(frames)} {frame['timestamp_ms']/1000:.2f}s {label} verified={annotations['verified']}"
            cv2.putText(canvas, "I/O: range  0-3: label  V: verify  S: save  Q: quit", (12,450), cv2.FONT_HERSHEY_SIMPLEX,.5,(200,200,200),1)
            cv2.putText(canvas, f"range: {mark_in} -> {mark_out}  {'UNSAVED' if dirty else ''}", (12,425), cv2.FONT_HERSHEY_SIMPLEX,.5,(200,200,200),1)
            key = preview(canvas, frame, text)
            if key == ord("q") or key == 27:
                if dirty:
                    print("Unsaved changes discarded. Press S before Q to save.")
                break
            if key == ord(" "):
                playing = not playing
            if key in (ord("a"),ord("d"),ord("j"),ord("l")):
                delta = {ord("a"):-1,ord("d"):1,ord("j"):-30,ord("l"):30}[key]
                index = max(0,min(len(frames)-1,index+delta))
                playing = False
            if key == ord("i"):
                mark_in = frame["timestamp_ms"]
            if key == ord("o"):
                mark_out = frames[index+1]["timestamp_ms"] if index+1<len(frames) else frame["timestamp_ms"]+1000/meta["fps"]
            if key in [ord(str(i)) for i in range(4)] and mark_in is not None and mark_out is not None and mark_out > mark_in:
                annotations["segments"] = replace_interval(annotations["segments"], mark_in, mark_out, LABELS[key-ord("0")])
                annotations["verified"] = False
                dirty = True
            if key == ord("v"):
                annotations["verified"] = not annotations["verified"]
                dirty = True
            if key == ord("s"):
                target = path / "annotations.json"
                backup = path / "annotations.previous.json"
                backup.write_text(target.read_text())
                target.write_text(json.dumps(annotations, indent=2))
                dirty = False
                print(f"Saved: {target}")
            if playing:
                import time
                if index+1<len(frames):
                    time.sleep(min(.1,max(0,(frames[index+1]["timestamp_ms"]-frame["timestamp_ms"])/1000)))
                    index += 1
                else:
                    playing = False
    finally:
        cv2.destroyAllWindows()
