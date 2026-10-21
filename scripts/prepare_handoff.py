import argparse
import csv
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from read_handoff import sha256, verify_package


ROOT = Path(__file__).resolve().parents[1]
LABELS = ["idle", "sculpt", "orbit", "resize"]
SIDES = ["Left", "Right"]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text())


def describe_file(path):
    return {"sha256": sha256(path), "bytes": Path(path).stat().st_size}


def session_arrays(frames, annotations, takes):
    if not annotations.get("verified"):
        raise ValueError("Annotations require completed human verification")
    n = len(frames)
    if n < 2:
        raise ValueError("Recording is too short")
    times = np.array([f["timestamp_ms"] for f in frames], dtype=np.float64)
    capture = np.array([f["capture_timestamp_ms"] for f in frames], dtype=np.float64)
    if not np.isfinite(times).all() or not np.isfinite(capture).all():
        raise ValueError("Timestamps must be finite")
    if np.any(np.diff(times) <= 0) or np.any(np.diff(capture) <= 0):
        raise ValueError("Timestamps must strictly increase")
    accepted = {t["take_id"]: t for t in takes if t["decision"] == "accepted"}
    take_ids = list(dict.fromkeys(f["take_id"] for f in frames))
    if set(take_ids) != set(accepted) or any(not t["complete"] for t in accepted.values()):
        raise ValueError("Frames must contain every complete accepted take, and no rejected takes")
    take_lookup = {name: i for i, name in enumerate(take_ids)}
    take_index = np.array([take_lookup[f["take_id"]] for f in frames], dtype=np.int32)
    if np.any(np.diff(take_index) < 0):
        raise ValueError("Each take must occupy one contiguous interval")
    end = max(t["end_ms"] for t in accepted.values())
    for name, index in take_lookup.items():
        t = accepted[name]
        selection = times[take_index == index]
        if len(selection) != t["frames"] or selection[0] < t["start_ms"] or selection[-1] >= t["end_ms"]:
            raise ValueError(f"Take manifest does not match frames: {name}")
    arrays = {"timestamp_ms": times, "capture_timestamp_ms": capture,
              "frame_index": np.arange(n, dtype=np.int64), "take_index": take_index,
              "take_ids": np.array(take_ids), "label": np.zeros(n, dtype=np.int8),
              "image": np.full((n, 2, 21, 3), np.nan, dtype=np.float64),
              "world": np.full((n, 2, 21, 3), np.nan, dtype=np.float64),
              "present": np.zeros((n, 2), dtype=bool), "valid": np.zeros((n, 2), dtype=bool),
              "score": np.full((n, 2), np.nan, dtype=np.float64),
              "detector_side": np.full((n, 2), "", dtype="U5")}
    for i, frame in enumerate(frames):
        for side, hand in frame.get("hands", {}).items():
            slot = SIDES.index(side)
            arrays["present"][i, slot] = True
            arrays["valid"][i, slot] = hand.get("valid", False)
            arrays["score"][i, slot] = hand["score"]
            if hand["side"] not in SIDES:
                raise ValueError("Unknown detector handedness")
            arrays["detector_side"][i, slot] = hand["side"]
            for key in ("image", "world"):
                coordinates = np.asarray(hand[key], dtype=np.float64)
                if coordinates.shape != (21, 3) or not np.isfinite(coordinates).all():
                    raise ValueError(f"Invalid {key} landmarks at frame {i}")
                arrays[key][i, slot] = coordinates
    previous_end = 0.0
    durations = {label: 0.0 for label in LABELS}
    event_counts = {label: 0 for label in LABELS[1:]}
    previous_segment = None
    for segment in sorted(annotations["segments"], key=lambda s: s["start_ms"]):
        start, stop, label = segment["start_ms"], segment["end_ms"], segment["label"]
        if not np.isfinite([start, stop]).all() or label not in LABELS or start < previous_end or stop <= start or stop > end + 1e-6:
            raise ValueError("Invalid annotation intervals")
        durations["idle"] += start - previous_end
        durations[label] += stop - start
        arrays["label"][(times >= start) & (times < stop)] = LABELS.index(label)
        if label != "idle" and (previous_segment is None or previous_segment["label"] != label or previous_end != start):
            event_counts[label] += 1
        previous_end, previous_segment = stop, segment
    durations["idle"] += end - previous_end
    same_take = take_index[1:] == take_index[:-1]
    intervals = np.diff(times)[same_take]
    summary = {"frames": n, "takes": len(take_ids), "duration_seconds": end / 1000,
               "effective_fps": n / (end / 1000), "median_capture_interval_ms": float(np.median(intervals)),
               "left_missing_fraction": float(1 - arrays["valid"][:, 0].mean()),
               "right_missing_fraction": float(1 - arrays["valid"][:, 1].mean()),
               "both_missing_fraction": float((~arrays["valid"].any(axis=1)).mean())}
    for label, i in zip(LABELS, range(4)):
        summary[f"{label}_frames"] = int((arrays["label"] == i).sum())
        summary[f"{label}_seconds"] = durations[label] / 1000
    summary.update({f"{label}_events": count for label, count in event_counts.items()})
    return arrays, summary


def export_session(source, package, reviewer, confirmed_at, smoothing):
    source_files = {name: describe_file(source / name) for name in
                    ("metadata.json", "frames.jsonl", "annotations.json", "recording_takes.json", "reference.mp4")}
    metadata = read_json(source / "metadata.json")
    annotations = read_json(source / "annotations.json")
    takes = read_json(source / "recording_takes.json")
    frames = [json.loads(line) for line in (source / "frames.jsonl").read_text().splitlines() if line.strip()]
    if metadata.get("synthetic") or metadata.get("mirrored") is not False:
        raise ValueError(f"Expected human, unmirrored recordings: {source.name}")
    if source.name != f"{metadata['subject']}_{metadata['session']}":
        raise ValueError("Directory and participant/session identifiers disagree")
    if any(f.get("dominant") != metadata["dominant"] or f.get("mirrored") is not False for f in frames):
        raise ValueError("Frame direction or dominant hand differs from metadata")
    arrays, summary = session_arrays(frames, annotations, takes)
    target = package / "data" / source.name
    target.mkdir(parents=True)
    provenance = package / "provenance" / source.name
    provenance.mkdir(parents=True)
    for name in ("metadata.json", "frames.jsonl", "annotations.json", "recording_takes.json", "reference.mp4"):
        if name != "reference.mp4":
            shutil.copy2(source / name, target / name)
            if describe_file(target / name) != source_files[name]:
                raise ValueError(f"Source changed during export: {source.name}/{name}")
    repairs = []
    for log in sorted(source.glob("tracking_repair*.json")):
        repair = read_json(log)
        backup = source / Path(repair["backup"]).name
        if sha256(backup) != repair["source_sha256"] or source_files["frames.jsonl"]["sha256"] != repair["corrected_sha256"]:
            raise ValueError(f"Tracking repair hashes do not match: {source.name}")
        for file in (log, backup):
            shutil.copy2(file, provenance / file.name)
            source_files[file.name] = describe_file(file)
        repairs.append({"log": f"provenance/{source.name}/{log.name}",
                        "original_frames": f"provenance/{source.name}/{backup.name}",
                        "frames_zero_based_inclusive": repair["frame_indices_zero_based_inclusive"],
                        "changed_frames": repair["changed_frames"], "operation": repair["operation"]})
    confirmation = {"reviewer": reviewer, "confirmation_recorded_at": confirmed_at,
                    "scope": "Entire session", "verified": True,
                    "annotations_sha256": source_files["annotations.json"]["sha256"],
                    "capture_smoothing": smoothing, "configuration_evidence": "User confirmation",
                    "additional_filter": "none"}
    write_json(provenance / "acceptance.json", confirmation)
    np.savez_compressed(target / "landmarks.npz", **arrays)
    with np.load(target / "landmarks.npz", allow_pickle=False) as saved:
        for key, expected in arrays.items():
            np.testing.assert_array_equal(saved[key], expected)
    summary = {"session_id": source.name, "subject": metadata["subject"],
               "session": metadata["session"], "dominant": metadata["dominant"],
               "configured_fps": metadata["fps"], "verified": True, **summary}
    return summary, {"source_files": source_files, "repairs": repairs, "acceptance": confirmation}


def make_archives(package, source_root, names, destination, version):
    destination.mkdir(parents=True, exist_ok=True)
    core = destination / f"airclay-data-{version}.zip"
    video = destination / f"airclay-videos-{version}.zip"
    for path in (core, video):
        if path.exists():
            raise FileExistsError(path)
    with zipfile.ZipFile(core, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path, str(Path(package.name) / path.relative_to(package)))
    with zipfile.ZipFile(video, "w", zipfile.ZIP_STORED) as archive:
        for name in names:
            archive.write(source_root / name / "reference.mp4", f"{package.name}/data/{name}/reference.mp4")
    return {path.name: describe_file(path) for path in (core, video)}


def build_package(data_root, output, snapshot, archive_dir, sessions, reviewer, smoothing, version):
    data_root, output, snapshot, archive_dir = map(Path, (data_root, output, snapshot, archive_dir))
    if smoothing != 1.0:
        raise ValueError("This release requires confirmed capture smoothing=1.0")
    if len(set(sessions)) != len(sessions) or any(Path(name).name != name or name in (".", "..") for name in sessions):
        raise ValueError("Use unique session directory names")
    expected_outputs = [output, snapshot, archive_dir / f"airclay-data-{version}.zip", archive_dir / f"airclay-videos-{version}.zip"]
    for path in expected_outputs:
        if path.exists():
            raise FileExistsError(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix=".handoff-", dir=output.parent) as temp:
        package = Path(temp) / output.name
        package.mkdir()
        shutil.copy2(ROOT / "docs/DATA_HANDOFF.md", package / "README.md")
        shutil.copy2(ROOT / "scripts/read_handoff.py", package / "read_handoff.py")
        summaries, provenance = [], {}
        for session in sessions:
            summary, evidence = export_session(data_root / session, package, reviewer, created, smoothing)
            summaries.append(summary)
            provenance[session] = evidence
            print(f"Prepared {session}: {summary['frames']} frames", flush=True)
        with (package / "inventory.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
        source_version = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        manifest = {"schema_version": 1, "dataset_id": f"airclay-{version}", "created_at": created,
                    "participants": sorted({row["subject"] for row in summaries}),
                    "frame_count": sum(row["frames"] for row in summaries), "sessions": summaries,
                    "labels": LABELS, "hand_slots": SIDES, "split": None,
                    "processing": {"capture_smoothing": smoothing, "evidence": "User confirmation",
                                   "additional_filter": "none", "resampled": False, "interpolated": False,
                                   "normalized": False, "windowed": False, "coordinate_dtype": "float64"},
                    "source_code": {"base_commit": source_version,
                                    "exporter_sha256": sha256(Path(__file__)),
                                    "reader_sha256": sha256(ROOT / "scripts/read_handoff.py")},
                    "provenance": provenance,
                    "files": {p.relative_to(package).as_posix(): describe_file(p)
                              for p in sorted(package.rglob("*")) if p.is_file()},
                    "video_files": {f"data/{s}/reference.mp4": provenance[s]["source_files"]["reference.mp4"] for s in sessions}}
        write_json(package / "manifest.json", manifest)
        verify_package(package)
        for session, evidence in provenance.items():
            for name, expected in evidence["source_files"].items():
                if describe_file(data_root / session / name) != expected:
                    raise ValueError(f"Source changed during export: {session}/{name}")
        package.rename(output)
    archives = make_archives(output, data_root, sessions, archive_dir, version)
    snapshot.mkdir(parents=True)
    for name in ("manifest.json", "inventory.csv", "README.md"):
        shutil.copy2(output / name, snapshot / name)
    for session in sessions:
        target = snapshot / "sessions" / session
        target.mkdir(parents=True)
        for name in ("metadata.json", "annotations.json", "recording_takes.json"):
            shutil.copy2(output / "data" / session / name, target / name)
        for path in (output / "provenance" / session).glob("*.json"):
            shutil.copy2(path, target / path.name)
    write_json(snapshot / "archives.json", {"archives": archives, "manifest_sha256": sha256(output / "manifest.json")})
    print(json.dumps({"package": str(output), "snapshot": str(snapshot), "archives": archives}, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--sessions", nargs="+", required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--capture-smoothing", type=float, required=True)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not args.version or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.version):
        parser.error("Version must contain only letters, digits, hyphens and underscores")
    build_package(args.data_root, ROOT / "data/processed" / f"airclay-{args.version}",
                  ROOT / "data/manifests" / f"airclay-{args.version}", ROOT / "dist",
                  args.sessions, args.reviewed_by, args.capture_smoothing, args.version)


if __name__ == "__main__":
    main()
