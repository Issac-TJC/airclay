import json
from types import SimpleNamespace

from airclay.config import config
from airclay.data_tools.synthetic import demo_frames


def test_interactive_recording_keeps_live_timestamps(monkeypatch, tmp_path):
    import cv2
    import airclay.tracking.camera as camera_module
    import airclay.interaction.protocol as protocol
    from airclay.data_tools.record import record

    frames, _ = demo_frames()
    frames = frames[:50]
    for i, frame in enumerate(frames):
        frame["timestamp_ms"] = 100000 + i * 37  # Deliberately not aligned to 30 Hz.
    original_times = [f["timestamp_ms"] for f in frames]
    emitted = []

    class FakeCamera:
        index = 0

        def __init__(self, *_):
            pass

        def read(self):
            frame = frames[self.index]
            self.index += 1
            return frame, None

        def close(self):
            pass

    class FakeSender:
        def __init__(self, *_):
            pass

        def send(self, frame, state):
            emitted.append(frame)

        def close(self):
            pass

    monkeypatch.setattr(camera_module, "Camera", FakeCamera)
    monkeypatch.setattr(camera_module, "preview", lambda image, frame, text: ord("q") if frame is frames[-1] else -1)
    monkeypatch.setattr(protocol, "Sender", FakeSender)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)
    args = SimpleNamespace(subject="p01", session="s01", output=str(tmp_path),
                           interact=True, guided=False, seconds=0, repetitions=1, video=False)
    record(args, config())

    assert [f["timestamp_ms"] for f in frames] == original_times
    assert all(len(f["hands"]) == 2 for f in emitted)
    saved = [json.loads(line) for line in (tmp_path / "p01_s01/frames.jsonl").read_text().splitlines()]
    assert saved[0]["timestamp_ms"] == 0
    assert saved[-1]["timestamp_ms"] == original_times[-1] - original_times[0]
