import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_handoff import build_package, session_arrays, write_json
from read_handoff import iter_takes, load_session, sha256, verify_package


@pytest.fixture
def recording(tmp_path):
    source = tmp_path / "source" / "p01_s01"
    source.mkdir(parents=True)
    hand = {"side": "Right", "valid": True, "score": 0.98,
            "image": np.arange(63).reshape(21, 3).tolist(),
            "world": (np.arange(63).reshape(21, 3) / 100).tolist()}
    frames = [{"timestamp_ms": t, "capture_timestamp_ms": c,
               "hands": {"Left": hand} if i in (1, 2, 4) else {},
               "dominant": "Right", "mirrored": False,
               "take_id": "takes/first" if i < 3 else "takes/second"}
              for i, (t, c) in enumerate(zip([0, 40, 80, 200, 250, 300], [1000, 1040, 1080, 3000, 3050, 3100]))]
    annotations = {"verified": True, "segments": [
        {"start_ms": 40, "end_ms": 80, "label": "sculpt"},
        {"start_ms": 200, "end_ms": 300, "label": "orbit"},
        {"start_ms": 300, "end_ms": 340, "label": "resize"}]}
    takes = [{"take_id": name, "decision": "accepted", "complete": True,
              "frames": 3, "start_ms": start, "end_ms": end}
             for name, start, end in [("takes/first", 0, 100), ("takes/second", 200, 340)]]
    (source / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    write_json(source / "metadata.json", {"subject": "p01", "session": "s01", "synthetic": False,
                                          "mirrored": False, "dominant": "Right", "fps": 30})
    write_json(source / "annotations.json", annotations)
    write_json(source / "recording_takes.json", takes)
    (source / "reference.mp4").write_bytes(b"unchanged video payload")
    return source, frames, annotations, takes


def test_arrays_preserve_slots_missing_frames_times_and_label_boundaries(recording):
    _, frames, annotations, takes = recording
    arrays, summary = session_arrays(frames, annotations, takes)
    assert arrays["image"].dtype == np.float64
    np.testing.assert_array_equal(arrays["image"][1, 0], frames[1]["hands"]["Left"]["image"])
    assert arrays["detector_side"][1, 0] == "Right"
    assert not arrays["present"][1, 1] and np.isnan(arrays["image"][1, 1]).all()
    assert not arrays["valid"][0].any()
    assert arrays["timestamp_ms"].tolist() == [0, 40, 80, 200, 250, 300]
    assert arrays["capture_timestamp_ms"].tolist() == [1000, 1040, 1080, 3000, 3050, 3100]
    assert arrays["label"].tolist() == [0, 1, 0, 2, 2, 3]
    assert arrays["frame_index"].tolist() == list(range(6))
    assert [len(t["label"]) for _, t in iter_takes(arrays)] == [3, 3]
    assert summary["median_capture_interval_ms"] == 45
    assert summary["idle_seconds"] == pytest.approx(0.16)


def test_rejects_unverified_or_rejected_input(recording):
    _, frames, annotations, takes = recording
    with pytest.raises(ValueError, match="human verification"):
        session_arrays(frames, {**annotations, "verified": False}, takes)
    takes[0]["decision"] = "rejected"
    with pytest.raises(ValueError, match="accepted take"):
        session_arrays(frames, annotations, takes)


def test_rejects_timestamp_and_annotation_errors(recording):
    _, frames, annotations, takes = recording
    broken = [{**f} for f in frames]
    broken[1]["timestamp_ms"] = 0
    with pytest.raises(ValueError, match="strictly increase"):
        session_arrays(broken, annotations, takes)
    annotations["segments"][1]["start_ms"] = 60
    with pytest.raises(ValueError, match="annotation intervals"):
        session_arrays(frames, annotations, takes)


def test_package_relocates_and_detects_damage_without_changing_sources(recording, tmp_path):
    source, _, _, _ = recording
    before = {p.name: sha256(p) for p in source.iterdir()}
    output = tmp_path / "processed" / "airclay-v1"
    snapshot = tmp_path / "snapshots" / "airclay-v1"
    dist = tmp_path / "dist"
    manifest = build_package(source.parent, output, snapshot, dist, [source.name], "Reviewer", 1.0, "v1")
    assert {p.name: sha256(p) for p in source.iterdir()} == before
    assert manifest["split"] is None and manifest["frame_count"] == 6
    assert not list(snapshot.rglob("*.npz")) and not list(snapshot.rglob("*.jsonl"))
    assert not list(output.rglob("*.mp4"))
    relocated = tmp_path / "other_machine"
    with zipfile.ZipFile(dist / "airclay-data-v1.zip") as archive:
        archive.extractall(relocated)
    with zipfile.ZipFile(dist / "airclay-videos-v1.zip") as archive:
        archive.extractall(relocated)
    root = relocated / "airclay-v1"
    assert verify_package(root, videos=True) == len(manifest["files"]) + 1
    arrays, meta = load_session(root, source.name)
    assert len(arrays["label"]) == 6 and meta["subject"] == "p01"
    assert (root / "data" / source.name / "reference.mp4").read_bytes() == b"unchanged video payload"
    with pytest.raises(FileExistsError):
        build_package(source.parent, output, snapshot, dist, [source.name], "Reviewer", 1.0, "v1")
    (root / "data" / source.name / "annotations.json").write_text("changed")
    with pytest.raises(ValueError, match="changed file"):
        verify_package(root)


def test_repair_backup_and_log_are_packaged_and_hash_checked(recording, tmp_path):
    source, _, _, _ = recording
    backup = source / "frames.before_fix.jsonl"
    backup.write_text("original coordinate backup\n")
    repair = {"backup": f"data/{source.name}/{backup.name}", "source_sha256": sha256(backup),
              "corrected_sha256": sha256(source / "frames.jsonl"),
              "frame_indices_zero_based_inclusive": [1, 2], "changed_frames": 2,
              "operation": "Exchange assigned Left and Right slots"}
    write_json(source / "tracking_repair.json", repair)
    output = tmp_path / "processed" / "airclay-v1"
    snapshot = tmp_path / "snapshot"
    manifest = build_package(source.parent, output, snapshot, tmp_path / "dist", [source.name], "Reviewer", 1.0, "v1")
    assert sha256(output / "provenance" / source.name / backup.name) == repair["source_sha256"]
    assert manifest["provenance"][source.name]["repairs"][0]["changed_frames"] == 2
    assert (snapshot / "sessions" / source.name / "tracking_repair.json").exists()
    repair["corrected_sha256"] = "wrong"
    write_json(source / "tracking_repair.json", repair)
    with pytest.raises(ValueError, match="repair hashes"):
        build_package(source.parent, tmp_path / "bad", tmp_path / "bad-snapshot", tmp_path / "bad-dist",
                      [source.name], "Reviewer", 1.0, "v2")
