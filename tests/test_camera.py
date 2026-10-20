"""The model, saved image and preview must share the raw camera orientation."""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from airclay.config import config
from airclay.data_tools.synthetic import hand
from airclay.tracking.camera import Camera, HandMatcher, preview


@pytest.mark.parametrize("side", ["Left", "Right"])
def test_camera_keeps_raw_pixels_landmarks_and_handedness(side, monkeypatch):
    observed = hand(.25, .5, side=side)
    model_result = SimpleNamespace(
        hand_landmarks=[[SimpleNamespace(x=x, y=y, z=z) for x, y, z in observed["image"]]],
        hand_world_landmarks=[[SimpleNamespace(x=x, y=y, z=z) for x, y, z in observed["world"]]],
        handedness=[[SimpleNamespace(category_name=side, score=.98)]],
    )
    # Asymmetric image makes an accidental horizontal flip observable.
    raw = np.zeros((240, 320, 3), dtype=np.uint8)
    raw[:, :160] = (30, 60, 90)
    raw[:, 160:] = (90, 60, 30)
    seen = []

    def detect(image, timestamp):
        seen.append(image.copy())
        return model_result

    camera = Camera.__new__(Camera)
    camera.cv2, camera.cfg = cv2, config()
    camera.mp = SimpleNamespace(Image=lambda **kwargs: kwargs["data"],
                                ImageFormat=SimpleNamespace(SRGB=1))
    camera.cap = SimpleNamespace(read=lambda: (True, raw.copy()))
    camera.detector = SimpleNamespace(detect_for_video=detect)
    camera.matcher, camera.last_t = HandMatcher(smoothing=1), -1
    frame, image = camera.read()

    np.testing.assert_array_equal(seen[0], cv2.cvtColor(raw, cv2.COLOR_BGR2RGB))
    np.testing.assert_array_equal(image, raw)
    assert frame["mirrored"] is False
    assert set(frame["hands"]) == {side}
    assert frame["hands"][side]["side"] == side
    np.testing.assert_array_equal(frame["hands"][side]["image"], observed["image"])
    np.testing.assert_array_equal(frame["hands"][side]["world"], observed["world"])

    shown, texts = [], []
    put_text = cv2.putText

    def capture_text(image, text, position, *args):
        texts.append((text, position))
        return put_text(image, text, position, *args)

    monkeypatch.setattr(cv2, "putText", capture_text)
    monkeypatch.setattr(cv2, "imshow", lambda title, image: shown.append(image.copy()))
    monkeypatch.setattr(cv2, "waitKey", lambda delay: ord("q"))
    assert preview(image.copy(), frame, "raw preview") == ord("q")
    np.testing.assert_array_equal(shown[0][-1], raw[-1])
    wrist = observed["image"][0]
    assert (side, (int(wrist[0] * 320), int(wrist[1] * 240))) in texts
