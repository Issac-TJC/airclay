import copy
import json

import pytest

from airclay.config import config
from airclay.data_tools.synthetic import hand_preview_frames
from airclay.interaction.protocol import build_packet, encode_packet, validate, PacketGate, preview_hands


def make_packet(frame=None, session="hand"):
    return build_packet(frame or hand_preview_frames()[0], {}, config("configs/hands.json"), session, 0, 0)


def test_full_skeleton_round_trip_and_no_global_depth():
    p = make_packet()
    assert p["profile"] == "hand_preview"
    assert p["local_world_space"] == "mediapipe_hand_centered_m"
    assert p["depth_available"] is False
    for hand in p["hands"].values():
        assert len(hand["image"]) == len(hand["local_world"]) == 21
        assert len(hand["image"][0]) == 2 and len(hand["local_world"][0]) == 3
    assert json.loads(encode_packet(p)) == p
    assert all(len(h["fingertips"]) == 5 for h in preview_hands(p).values())


def test_hand_packet_worst_size_and_validity_boundaries():
    p = make_packet()
    p["session"] = "s" * 100
    for h in p["hands"].values():
        h["image"] = [[-3.123456, -3.123456] for _ in range(21)]
        h["local_world"] = [[-1.123456] * 3 for _ in range(21)]
    assert len(encode_packet(p)) < 4096
    for frame in hand_preview_frames():
        assert len(encode_packet(make_packet(frame))) < 4096


@pytest.mark.parametrize("change", [
    lambda p: p.update(local_world_space="camera_space"),
    lambda p: p.update(depth_available=True),
    lambda p: p["hands"]["Left"]["image"].pop(),
    lambda p: p["hands"]["Left"]["local_world"][3].append(0),
    lambda p: p["hands"]["Left"]["local_world"][3].__setitem__(0, float("nan")),
    lambda p: p["hands"]["Left"].update(valid=False),
])
def test_bad_skeleton_rejected(change):
    p = make_packet()
    change(p)
    with pytest.raises(ValueError):
        validate(p)


def test_missing_bad_skeleton_clears_whole_hand_and_recovery_is_complete():
    frame = hand_preview_frames()[0]
    frame["hands"]["Right"]["world"][3][0] = float("nan")
    del frame["hands"]["Left"]
    p = make_packet(frame)
    assert all(h == {"valid": False, "image": None, "local_world": None} for h in p["hands"].values())
    assert all(not h["valid"] for h in preview_hands(p).values())
    assert all(h["valid"] for h in make_packet()["hands"].values())


def test_profiles_cannot_switch_in_same_session():
    gate = PacketGate()
    assert gate.accept(make_packet())
    frame = hand_preview_frames()[0]
    hover = build_packet(frame, {}, config("configs/hover.json"), "hand", 1, 1)
    assert not gate.accept(hover)
    hover["session"] = "hover"
    assert gate.accept(hover)
    stale = copy.deepcopy(make_packet())
    stale["seq"] = 100
    assert not gate.accept(stale)
