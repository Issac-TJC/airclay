#!/usr/bin/env python3
"""Derive a filtered copy of an AirClay handoff release, offline and causally.

Only landmark coordinates change. Hand identities (slots), timestamps, takes, validity and
labels are copied unchanged, and missing hands stay missing. The EMA matches
airclay.tracking.camera.HandMatcher: p_hat = alpha * p + (1 - alpha) * p_hat_prev for both
"image" and "world", applied only when the same hand was seen less than gap_ms earlier
(capture time). Filter state also resets at every take boundary, because the stitched
timestamp_ms timeline hides the pauses between takes.

Usage (from the repository root):
    python3 scripts/derive_filtered.py data/processed/airclay-v1 data/processed/airclay-v1-ema --filter ema
    python3 scripts/derive_filtered.py ... --check-online   # compare with HandMatcher(smoothing=alpha)
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

SIDES = ("Left", "Right")
KEYS = ("image", "world")
COPIED = ("metadata.json", "annotations.json", "recording_takes.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_frames(folder):
    return [json.loads(line) for line in (folder / "frames.jsonl").read_text().splitlines() if line.strip()]


def ema_frames(frames, alpha, gap_ms):
    """Return (filtered frames, stats). Same arithmetic as HandMatcher.update."""
    previous = {}  # side -> (take_id, capture_ms, {key: smoothed array})
    stats = {"observations": 0, "smoothed": 0, "resets_after_gap": 0, "resets_at_take": 0}
    out = []
    for frame in frames:
        t, take = float(frame["capture_timestamp_ms"]), frame["take_id"]
        hands = {}
        for side, hand in frame.get("hands", {}).items():
            hand = dict(hand)
            stats["observations"] += 1
            old = previous.get(side)
            if old and old[0] == take and t - old[1] < gap_ms:
                for key in KEYS:
                    hand[key] = (alpha * np.array(hand[key]) + (1 - alpha) * np.array(old[2][key])).tolist()
                stats["smoothed"] += 1
            elif old and old[0] != take:
                stats["resets_at_take"] += 1
            elif old:
                stats["resets_after_gap"] += 1
            previous[side] = (take, t, {key: hand[key] for key in KEYS})
            hands[side] = hand
        frame = dict(frame)
        frame["hands"] = hands
        out.append(frame)
    return out, stats


def kalman_frames(frames, q, r, gap_ms, v0_var=1.0):
    """Constant-velocity Kalman filter per coordinate, with the same resets as ema_frames.

    State per coordinate: [position, velocity]. Prediction uses the real interval dt (seconds)
    between two observations of the same hand; Q is continuous white-noise acceleration with
    spectral density q, R = r. The gain depends only on q, r and dt, so one covariance per hand
    serves all 2 x 21 x 3 coordinates. A reset starts from the measured position, zero velocity.
    """
    previous = {}  # side -> (take_id, capture_ms, P (2x2), {key: (position, velocity)})
    stats = {"observations": 0, "smoothed": 0, "resets_after_gap": 0, "resets_at_take": 0}
    out = []
    for frame in frames:
        t, take = float(frame["capture_timestamp_ms"]), frame["take_id"]
        hands = {}
        for side, hand in frame.get("hands", {}).items():
            hand = dict(hand)
            stats["observations"] += 1
            old = previous.get(side)
            if old and old[0] == take and t - old[1] < gap_ms:
                dt = (t - old[1]) / 1000.0
                F = np.array([[1.0, dt], [0.0, 1.0]])
                Q = q * np.array([[dt ** 3 / 3, dt ** 2 / 2], [dt ** 2 / 2, dt]])
                P = F @ old[2] @ F.T + Q
                K = P[:, 0] / (P[0, 0] + r)               # gain for H = [1, 0]
                states = {}
                for key in KEYS:
                    p, v = old[3][key]
                    p_pred = p + v * dt
                    innovation = np.array(hand[key]) - p_pred
                    p, v = p_pred + K[0] * innovation, v + K[1] * innovation
                    states[key] = (p, v)
                    hand[key] = p.tolist()
                P = P - np.outer(K, P[0, :])               # (I - K H) P
                stats["smoothed"] += 1
            else:
                if old and old[0] != take:
                    stats["resets_at_take"] += 1
                elif old:
                    stats["resets_after_gap"] += 1
                P = np.array([[r, 0.0], [0.0, v0_var]])
                states = {key: (np.array(hand[key], dtype=np.float64), np.zeros((21, 3))) for key in KEYS}
            previous[side] = (take, t, P, states)
            hands[side] = hand
        frame = dict(frame)
        frame["hands"] = hands
        out.append(frame)
    return out, stats


def write_session(source, target, frames):
    target.mkdir(parents=True, exist_ok=False)
    for name in COPIED:
        shutil.copy2(source / name, target / name)
    (target / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    with np.load(source / "landmarks.npz", allow_pickle=False) as saved:
        arrays = {key: saved[key].copy() for key in saved.files}
    if len(arrays["timestamp_ms"]) != len(frames):
        raise ValueError(f"{source.name}: landmarks.npz and frames.jsonl differ in length")
    for i, frame in enumerate(frames):
        if arrays["timestamp_ms"][i] != frame["timestamp_ms"]:
            raise ValueError(f"{source.name}: frame {i} timestamp mismatch")
        for side, hand in frame["hands"].items():
            slot = SIDES.index(side)
            if not arrays["present"][i, slot]:
                raise ValueError(f"{source.name}: frame {i} {side} not present in landmarks.npz")
            for key in KEYS:
                arrays[key][i, slot] = np.asarray(hand[key], dtype=np.float64)
    np.savez_compressed(target / "landmarks.npz", **arrays)


def check_online(frames, filtered, alpha):
    """Replay raw detections through the live HandMatcher and compare with the offline result."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from airclay.tracking.camera import HandMatcher
    matcher = HandMatcher(alpha)
    identical, different, assignment_differs, max_diff = 0, 0, 0, 0.0
    for raw, offline in zip(frames, filtered):
        detections = [{"side": h["side"], "score": h["score"], "image": h["image"], "world": h["world"]}
                      for h in raw.get("hands", {}).values()]
        live = matcher.update(detections, int(raw["capture_timestamp_ms"]))
        if {s: h["side"] for s, h in live.items()} != {s: h["side"] for s, h in offline["hands"].items()}:
            assignment_differs += 1
        for side, hand in offline["hands"].items():
            if side not in live:
                different += 1
                continue
            diff = max(float(np.max(np.abs(np.array(live[side][key]) - np.array(hand[key])))) for key in KEYS)
            max_diff = max(max_diff, diff)
            if diff == 0.0:
                identical += 1
            else:
                different += 1
    return {"identical_observations": identical, "different_observations": different,
            "frames_where_live_assignment_differs": assignment_differs, "max_abs_diff": max_diff}


def git_version(repo):
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        return {"commit": head, "dirty": bool(dirty)}
    except Exception:
        return {"commit": None, "dirty": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path, help="raw release root, e.g. data/processed/airclay-v1")
    ap.add_argument("output", type=Path, help="new release root, e.g. data/processed/airclay-v1-ema")
    ap.add_argument("--filter", choices=["ema", "kalman"], default="ema")
    ap.add_argument("--alpha", type=float, default=0.45, help="EMA weight of the new observation")
    ap.add_argument("--q", type=float, default=None, help="Kalman white-noise acceleration spectral density")
    ap.add_argument("--r", type=float, default=None, help="Kalman measurement noise variance")
    ap.add_argument("--v0-var", type=float, default=1.0, help="Kalman initial velocity variance after a reset")
    ap.add_argument("--gap-ms", type=float, default=150.0)
    ap.add_argument("--check-online", action="store_true", help="EMA only: compare with HandMatcher")
    a = ap.parse_args()
    if a.output.exists():
        sys.exit(f"{a.output} already exists; refusing to overwrite")
    if a.filter == "kalman" and (a.q is None or a.r is None):
        sys.exit("--filter kalman needs --q and --r (choose them on validation data)")
    if a.check_online and a.filter != "ema":
        sys.exit("--check-online compares against HandMatcher, which only implements EMA")
    sessions = sorted(p.parent.name for p in (a.source / "data").glob("*/frames.jsonl"))
    repo = Path(__file__).resolve().parents[1]
    reset = "every take and after gaps >= gap_ms (capture time)"
    if a.filter == "ema":
        description = {"name": "ema", "alpha": a.alpha, "gap_ms": a.gap_ms, "reset": reset,
                       "formula": "p_hat = alpha * p + (1 - alpha) * p_hat_prev, applied to image and world landmarks"}
    else:
        description = {"name": "kalman", "q": a.q, "r": a.r, "v0_var": a.v0_var, "gap_ms": a.gap_ms, "reset": reset,
                       "model": "constant velocity per coordinate, state [position, velocity], H = [1, 0], "
                                "Q = q * [[dt^3/3, dt^2/2], [dt^2/2, dt]], R = r, dt = real interval in seconds; "
                                "reset to the measured position with zero velocity and P = diag(r, v0_var)"}
    manifest = {
        "dataset": a.output.name, "derived_from": a.source.name,
        "source_manifest_sha256": sha256(a.source / "manifest.json"),
        "filter": description,
        "unchanged": ["hand slots/identities", "timestamps", "takes", "valid/present flags", "scores", "labels", "annotations"],
        "not_copied": ["reference.mp4 (use the raw release for video review)"],
        "script": {"path": "scripts/derive_filtered.py", "sha256": sha256(Path(__file__).resolve()), "repo": git_version(repo)},
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sessions": {},
    }
    for name in sessions:
        source, target = a.source / "data" / name, a.output / "data" / name
        frames = read_frames(source)
        if a.filter == "ema":
            filtered, stats = ema_frames(frames, a.alpha, a.gap_ms)
        else:
            filtered, stats = kalman_frames(frames, a.q, a.r, a.gap_ms, a.v0_var)
        write_session(source, target, filtered)
        entry = {"frames": len(frames), **stats,
                 "files": {f.name: sha256(f) for f in sorted(target.iterdir())}}
        if a.check_online:
            entry["online_check"] = check_online(frames, filtered, a.alpha)
        manifest["sessions"][name] = entry
        print(name, json.dumps({k: v for k, v in entry.items() if k != "files"}))
    shutil.copy2(a.source / "read_handoff.py", a.output / "read_handoff.py")
    (a.output / "derived_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("wrote", a.output)


if __name__ == "__main__":
    main()
