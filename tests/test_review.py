import hashlib
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from airclay.data_tools.review import Playback, ReferenceVideo, review, review_groups


def test_playback_uses_capture_time_and_stops_before_next_take():
    frames = [{"timestamp_ms": t, "take_id": take} for t, take in
              [(0, "round1"), (67, "round1"), (201, "round1"), (235, "round2"), (302, "round2")]]
    takes = [{"take_id": "rejected", "decision": "rejected", "kind": "round", "round": 1},
             {"take_id": "round1", "decision": "accepted", "kind": "round", "round": 1},
             {"take_id": "round2", "decision": "accepted", "kind": "round", "round": 2}]
    state = Playback(frames, review_groups(frames, takes))
    assert len(state.groups) == 2
    state.jump(0, 10)
    state.advance(10.034)  # A 30 FPS video would have advanced, but capture did not.
    assert state.index == 0
    state.advance(10.067)
    assert state.index == 1
    assert state.deadline == pytest.approx(10.201)
    state.advance(10.202)
    assert state.index == 2
    assert not state.playing
    state.advance(99)
    assert state.index == 2
    state.speed = .5
    state.jump(1, 100)
    assert state.index == 3
    assert state.deadline == pytest.approx(100.134)
    state.step(-1)
    assert state.index == 3  # Stepping stays in the current round.
    assert not state.playing


def make_video(path):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (64, 48))
    assert writer.isOpened()
    for level in [20, 100, 220]:
        writer.write(np.full((48, 64, 3), level, dtype=np.uint8))
    writer.release()


def test_video_seeks_by_frame_index_and_rejects_mismatched_count(tmp_path):
    path = tmp_path / "reference.mp4"
    make_video(path)
    video = ReferenceVideo(path, 3)
    try:
        for index, expected in [(0, 20), (2, 220), (1, 100), (1, 100)]:
            assert abs(float(video.read(index).mean()) - expected) < 8
    finally:
        video.close()
    with pytest.raises(ValueError, match="exactly 4 frames"):
        ReferenceVideo(path, 4)


def test_review_flag_never_edits_annotations_or_verification(monkeypatch, tmp_path):
    make_video(tmp_path / "reference.mp4")
    frames = [{"timestamp_ms": t, "hands": {}} for t in (0, 67, 201)]
    (tmp_path / "frames.jsonl").write_text("\n".join(json.dumps(f) for f in frames))
    (tmp_path / "metadata.json").write_text(json.dumps({"fps": 30}))
    annotation_path = tmp_path / "annotations.json"
    annotation_path.write_text(json.dumps({"verified": False, "segments": [
        {"start_ms": 0, "end_ms": 67, "label": "idle"},
        {"start_ms": 67, "end_ms": 250, "label": "resize"}]}))
    original = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    keys = iter([ord("d"), ord("f"), ord("q")])
    for name in ["namedWindow", "resizeWindow", "imshow", "destroyAllWindows"]:
        monkeypatch.setattr(cv2, name, lambda *args: None)
    monkeypatch.setattr(cv2, "getWindowProperty", lambda *args: 1)
    monkeypatch.setattr(cv2, "waitKey", lambda *args: next(keys))
    review(SimpleNamespace(recordings=[str(tmp_path)]))
    for name, contents in original.items():
        assert (tmp_path / name).read_bytes() == contents
    flag = json.loads((tmp_path / "human_review_flags.jsonl").read_text())
    assert flag["frame_index"] == 1
    assert flag["timestamp_ms"] == 67
    assert flag["label"] == "resize"
    assert flag["annotations_sha256"] == hashlib.sha256(original["annotations.json"]).hexdigest()
