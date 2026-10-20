import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from airclay.config import config
from airclay.data_tools.guided import RoundSchedule
from airclay.data_tools.record import record


@pytest.fixture(autouse=True)
def accept_guide(monkeypatch):
    import airclay.data_tools.recording_guide as guide
    monkeypatch.setattr(guide, "show_recording_guide", lambda *args: True)


def test_round_cues_include_release_time_and_wait_for_confirmation():
    schedule = RoundSchedule(1, 20)
    assert "SCULPT in 5.0s" in schedule.cue(0).text
    assert schedule.cue(4999).label == "idle"
    assert schedule.cue(5000).label == "sculpt"
    assert "ORBIT in 6.0s" in schedule.cue(5000).text
    assert schedule.cue(9000).label == "idle"
    assert "ORBIT in 2.0s" in schedule.cue(9000).text
    assert schedule.cue(11000).label == "orbit"
    assert "RESIZE in 6.0s" in schedule.cue(11000).text
    assert schedule.cue(17000).label == "resize"
    assert "PAUSE" in schedule.cue(17000).text
    assert schedule.cue(21000).phase == "release"
    assert schedule.cue(23000).phase == "review"
    assert schedule.cue(23000) == schedule.cue(500000)
    assert "R  Retry" in schedule.cue(23000).controls
    assert "NATURAL MOVEMENT" in RoundSchedule(20, 20).cue(23000).text
    natural = RoundSchedule(21, 20)
    assert natural.cue(0).phase == "prepare"
    assert natural.cue(5000).phase == "natural"
    assert natural.cue(124999).phase == "natural"
    assert natural.cue(125000).phase == "done"
    left = RoundSchedule(1, 20, prepare_seconds=8, dominant="Left")
    assert "SCULPT in 8.0s" in left.cue(0).text
    assert "SCULPT (Left)" in left.cue(8000).text
    assert "ORBIT (Right)" in left.cue(14000).text


def fake_camera(monkeypatch, frames, keys, colors=None):
    import airclay.tracking.camera as camera_module
    previews, closed = [], []
    source = iter(enumerate(frames))

    class Camera:
        def __init__(self, *_):
            pass

        def read(self):
            i, frame = next(source)
            image = np.full((48, 64, 3), colors[i] if colors else 25, dtype=np.uint8)
            return frame, image

        def close(self):
            closed.append(True)

    def preview(image, frame, text, controls=""):
        previews.append((frame["timestamp_ms"], text))
        # Verify the video was saved before any preview overlays.
        image[:] = 255
        return keys.get(frame["timestamp_ms"], -1)

    monkeypatch.setattr(camera_module, "Camera", Camera)
    monkeypatch.setattr(camera_module, "preview", preview)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)
    return previews, closed


def arguments(tmp_path, **changes):
    return SimpleNamespace(**{**dict(subject="p01", session="s01", output=str(tmp_path),
                           interact=False, guided=True, seconds=0, repetitions=1,
                           prepare_seconds=5, video=False), **changes})


@pytest.mark.parametrize("repetitions,video", [(1, False), (2, True)])
def test_retry_pause_accept_and_natural_recording(monkeypatch, tmp_path, repetitions, video):
    import airclay.interaction.protocol as protocol
    import airclay.interaction.runner as runner
    from airclay.data_tools.dataset import read_recording

    frames, keys, colors, keep, recorded = [], {}, [], [], []

    def add(t, color, key=-1, save=False, accepted=False):
        frames.append({"timestamp_ms": t, "hands": {}, "dominant": "Right", "mirrored": False})
        colors.append(color)
        keys[t] = key
        if save:
            recorded.append(t)
        if accepted:
            keep.append(t)

    base = 1000000
    for attempt in range(repetitions + 1):
        rejected = attempt == 0
        color = (0, 0, 200) if rejected else (200, 0, 0)
        for t in range(0, 23000, 1000):
            add(base + t, color, ord("n") if t == 5000 else -1, True, not rejected)
        add(base + 23000, color)  # Pause, without a choice, never auto-advances.
        add(base + 100000, color, ord("r") if rejected else ord("n"))
        base += 101000
    for t in (0, 5000, 124000):
        add(base + t, (0, 180, 0), save=True, accepted=True)
    add(base + 125000, (0, 180, 0))
    original_times = [f["timestamp_ms"] for f in frames]
    previews, closed = fake_camera(monkeypatch, frames, keys, colors)
    senders, pipelines, emitted = [], [], []

    class Sender:
        def __init__(self, *_):
            self.closed = False
            senders.append(self)

        def send(self, frame, state):
            assert not self.closed
            emitted.append(frame)

        def close(self):
            self.closed = True

    class Pipeline:
        def __init__(self, *_):
            pipelines.append(self)

        def step(self, frame):
            return [(frame, {})]

    monkeypatch.setattr(protocol, "Sender", Sender)
    monkeypatch.setattr(runner, "Pipeline", Pipeline)
    record(arguments(tmp_path, repetitions=repetitions, video=video, interact=True), config())
    folder = tmp_path / "p01_s01"
    meta, saved, ann = read_recording(folder)
    takes = json.loads((folder / "recording_takes.json").read_text())

    assert closed == [True]
    assert meta["mirrored"] is False and meta["prepare_seconds"] == 5
    assert [f["timestamp_ms"] for f in frames] == original_times
    assert [f["timestamp_ms"] for f in emitted] == recorded
    assert len(senders) == len(pipelines) == repetitions + 2
    assert all(sender.closed for sender in senders)
    assert [f["capture_timestamp_ms"] for f in saved] == keep
    assert all(b["timestamp_ms"] > a["timestamp_ms"] for a, b in zip(saved, saved[1:]))
    assert saved[0]["timestamp_ms"] == 0
    assert all("take_id" in f and f["mirrored"] is False for f in saved)
    assert [t["decision"] for t in takes] == ["rejected"] + ["accepted"] * (repetitions + 1)
    assert [t["round"] for t in takes] == [1] + list(range(1, repetitions + 2))
    assert takes[1]["attempt"] == 2
    assert all(t["complete"] for t in takes)
    assert ann["verified"] is False
    for label in ("sculpt", "orbit", "resize"):
        assert sum(s["label"] == label for s in ann["segments"]) == repetitions
    rejected = folder / takes[0]["take_id"]
    assert len((rejected / "frames.jsonl").read_text().splitlines()) == 23
    assert "PAUSED" in dict(previews)[1000000 + 100000]
    assert "Round 1/" in dict(previews)[1101000]
    assert "GET READY" in dict(previews)[1101000]
    if video:
        cap = cv2.VideoCapture(str(folder / "reference.mp4"))
        decoded = []
        while True:
            ok, image = cap.read()
            if not ok:
                break
            decoded.append(image.mean(axis=(0, 1)))
        cap.release()
        assert len(decoded) == len(saved)
        assert all(pixel[0] > 150 and pixel[2] < 20 for pixel in decoded[:-3])
        assert all(pixel[1] > 150 and pixel[2] < 20 for pixel in decoded[-3:])
        assert (rejected / "reference.mp4").is_file()
    else:
        assert not list(folder.rglob("*.mp4"))


@pytest.mark.parametrize("quit_time", [5000, 23000])
def test_quit_discards_current_recording(monkeypatch, tmp_path, quit_time):
    earlier = tmp_path / "p01_s00"
    earlier.mkdir()
    (earlier / "frames.jsonl").write_text("previous recording")
    times = [t for t in range(0, 23000, 1000) if t < quit_time] + [quit_time]
    frames = [{"timestamp_ms": t, "hands": {}} for t in times]
    fake_camera(monkeypatch, frames, {quit_time: ord("q")})
    record(arguments(tmp_path), config())
    folder = tmp_path / "p01_s01"
    assert not folder.exists()
    assert list((tmp_path / ".inprogress").iterdir()) == []
    assert (earlier / "frames.jsonl").read_text() == "previous recording"


def test_quit_after_accepted_round_discards_video_and_all_rounds(monkeypatch, tmp_path):
    times = list(range(0, 24000, 1000)) + [24000, 29000]
    frames = [{"timestamp_ms": t, "hands": {}} for t in times]
    _, closed = fake_camera(monkeypatch, frames, {23000: ord("n"), 29000: ord("q")})
    record(arguments(tmp_path, video=True), config())
    assert closed == [True]
    assert not (tmp_path / "p01_s01").exists()
    assert list((tmp_path / ".inprogress").iterdir()) == []


def test_camera_failure_keeps_recovery_files_outside_dataset(monkeypatch, tmp_path):
    def frames():
        yield {"timestamp_ms": 1000, "hands": {}}
        raise RuntimeError("Camera disconnected")
    fake_camera(monkeypatch, frames(), {})
    with pytest.raises(RuntimeError, match="Camera disconnected"):
        record(arguments(tmp_path), config())
    assert not (tmp_path / "p01_s01").exists()
    recovery, = (tmp_path / ".inprogress").iterdir()
    assert (recovery / "frames.jsonl").read_text().strip()
    assert (recovery / "metadata.json").exists()
    assert list(tmp_path.glob("*/metadata.json")) == []


@pytest.mark.parametrize("changes", [{"repetitions": 0}, {"prepare_seconds": 0},
                                   {"prepare_seconds": float("nan")}, {"prepare_seconds": float("inf")}])
def test_invalid_schedule_does_not_create_output(tmp_path, changes):
    with pytest.raises(ValueError):
        record(arguments(tmp_path, **changes), config())
    assert not (tmp_path / "p01_s01").exists()
