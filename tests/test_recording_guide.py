from types import SimpleNamespace

import cv2
import pytest

from airclay.config import config
from airclay.data_tools.record import record
from airclay.data_tools import recording_guide as guide


def arguments(tmp_path):
    return SimpleNamespace(subject="p01", session="s01", output=str(tmp_path),
                           guided=True, repetitions=20, prepare_seconds=5,
                           interact=False, seconds=0, video=False)


def test_guide_uses_instructions_without_launch_commands():
    pages = guide.guide_pages()
    text = " ".join(title + " " + " ".join(lines) for title, lines in pages)
    assert "SCULPT" in text and "ORBIT" in text and "RESIZE" in text
    assert "NATURAL MOVEMENT" in text and "Q DOES NOT SAVE" in text
    assert "BEFORE the OPEN HANDS countdown ends" in text
    assert "Start recording" not in text and ".venv/bin" not in text
    for _, lines in pages:
        assert len(lines) <= 18
        assert all(cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, .56, 1)[0][0] <= guide.BODY_WIDTH for line in lines)


def test_continue_requires_clicking_the_final_page(monkeypatch, tmp_path):
    callback, shown, closed = [], [], []
    monkeypatch.setattr(cv2, "namedWindow", lambda *args: None)
    monkeypatch.setattr(cv2, "setMouseCallback", lambda window, fn: callback.append(fn))
    monkeypatch.setattr(cv2, "imshow", lambda *args: None)
    monkeypatch.setattr(cv2, "getWindowProperty", lambda *args: 1)
    monkeypatch.setattr(cv2, "destroyWindow", lambda name: closed.append(name))
    monkeypatch.setattr(guide, "guide_image", lambda pages, index, *args: shown.append(index))

    def press_key_or_click(delay):
        # Neither Enter nor Space may bypass the required Continue click.
        if len(shown) <= 2:
            return 13 if len(shown) == 1 else ord(" ")
        callback[0](cv2.EVENT_LBUTTONUP, guide.NEXT[0] + 10, guide.NEXT[1] + 10, 0, None)
        return -1

    monkeypatch.setattr(cv2, "waitKey", press_key_or_click)
    assert guide.show_recording_guide(arguments(tmp_path), config()) is True
    assert shown[:3] == [0, 0, 0]
    assert shown[2:] == list(range(len(guide.guide_pages())))
    assert closed == [guide.WINDOW]


def test_cancelling_guide_never_opens_camera_or_creates_recording(monkeypatch, tmp_path):
    import airclay.tracking.camera as camera_module
    monkeypatch.setattr(guide, "show_recording_guide", lambda *args: False)

    def unexpected_camera(*args):
        pytest.fail("Camera must stay closed until Continue is clicked")

    monkeypatch.setattr(camera_module, "Camera", unexpected_camera)
    record(arguments(tmp_path), config())
    assert list(tmp_path.iterdir()) == []


def test_existing_session_is_never_overwritten(monkeypatch, tmp_path):
    folder = tmp_path / "p01_s01"
    folder.mkdir()
    (folder / "frames.jsonl").write_text("existing recording")
    monkeypatch.setattr(guide, "show_recording_guide", lambda *args: pytest.fail("Should reject existing session first"))
    with pytest.raises(FileExistsError):
        record(arguments(tmp_path), config())
    assert (folder / "frames.jsonl").read_text() == "existing recording"
