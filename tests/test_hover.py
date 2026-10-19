import json

import numpy as np
import pytest

from airclay.config import config
from airclay.data_tools.synthetic import demo_frames, hand, hover_frames
from airclay.interaction.protocol import (
    FINGERTIPS, FINGER_LABELS, HAND_COLORS, MAX_PACKET_BYTES, PacketGate,
    build_packet, encode_packet, image_to_region, validate,
)
from airclay.interaction.runner import Pipeline
from airclay.tracking.camera import HandMatcher, mirror_camera_image


def packet(session="preview", seq=0):
    frame = {"timestamp_ms": 1000, "hands": {
        "Left": hand(.4, .5, side="Left"), "Right": hand(.6, .5)}}
    return build_packet(frame, {}, {**config(), "interaction_version": 2}, session, seq, 1001)


def test_preview_packet_ids_depth_and_round_trip():
    p = packet()
    assert FINGERTIPS == {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
    assert list(FINGER_LABELS.values()) == list("TIMRP")
    for h in p["hands"].values():
        assert [t["finger_id"] for t in h["fingertips"]] == list(FINGERTIPS)
        assert all(t["xyz"] is None and t["depth_confidence"] is None for t in h["fingertips"])
    assert p["depth_available"] is False
    assert "mode" not in p and "operation_id" not in p
    assert validate(json.loads(encode_packet(p))) == p
    # Long session and maximum normalized-coordinate precision still fit.
    p["session"] = "s" * 100
    for h in p["hands"].values():
        for tip in h["fingertips"]:
            tip["xy"] = [.123456, .987654]
    assert len(encode_packet(p)) < MAX_PACKET_BYTES


def test_unordered_and_missing_tips_are_valid_snapshots():
    p = packet()
    p["hands"]["Left"]["fingertips"].reverse()
    p["hands"]["Right"]["fingertips"] = []
    assert validate(p) is p


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(version=3),
    lambda p: p.update(version=True),
    lambda p: p.update(profile="object_grip"),
    lambda p: p.update(mode="sculpt"),
    lambda p: p.update(depth_available=True),
    lambda p: p.update(coordinate_space="camera"),
    lambda p: p.update(sent_ms=float("nan")),
    lambda p: p.update(timestamp_ms=10 ** 1000),
    lambda p: p.update(timestamp_ms=True),
    lambda p: p.update(seq=-1),
    lambda p: p["hands"].pop("Left"),
    lambda p: p["hands"]["Left"].update(valid=False),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(finger_id="index"),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(finger_id="unknown"),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(xy=[float("nan"), .5]),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(xy=[1.01, .5]),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(xy=[-.01, .5]),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(xy=[True, .5]),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(xy=None),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(xyz=[0, 0, .45]),
    lambda p: p["hands"]["Left"]["fingertips"][0].update(depth_confidence=.8),
])
def test_preview_rejects_malformed_or_unsupported_data(mutation):
    p = packet()
    mutation(p)
    with pytest.raises(ValueError):
        validate(p)


def test_preview_gate_order_sessions_and_version_isolation():
    gate = PacketGate()
    assert gate.accept(packet(seq=3))
    assert not gate.accept(packet(seq=3))
    assert not gate.accept(packet(seq=2))
    frame = {"timestamp_ms": 1000, "hands": {}}
    state = {"mode": "idle", "operation_id": 0, "paused": False, "outcome": None}
    v1 = build_packet(frame, state, config(), "preview", 4)
    assert not gate.accept(v1)
    assert gate.accept(packet("new"))
    assert not gate.accept(packet(seq=100))
    invalid = packet("invalid", 50)
    invalid["hands"]["Left"]["fingertips"][0]["xy"] = [float("nan"), 0]
    with pytest.raises(ValueError):
        gate.accept(invalid)
    assert gate.session == "new" and gate.seq == 0


def test_mirrored_image_region_coordinates_and_hand_identity():
    image = np.arange(18).reshape(2, 3, 3)
    before = image.copy()
    mirrored = mirror_camera_image(image)
    np.testing.assert_array_equal(mirrored[:, 0], before[:, -1])
    np.testing.assert_array_equal(image, before)
    assert image_to_region((.25, .1), 800, 600) == (200, 540)
    assert image_to_region((.25, .1), 1600, 1200) == (400, 1080)
    assert image_to_region((0, 0), 800, 600) == (0, 600)
    assert image_to_region((1, 1), 800, 600) == (800, 0)
    assert HAND_COLORS["Left"][2] > HAND_COLORS["Left"][0]
    assert HAND_COLORS["Right"][0] > HAND_COLORS["Right"][2]
    matcher = HandMatcher()
    original = matcher.update([hand(.3, .5, side="Left"), hand(.7, .5)], 0)
    flipped = matcher.update([hand(.31, .5, side="Right"), hand(.69, .5, side="Left")], 33)
    cfg = {**config(), "interaction_version": 2}
    for hands in (original, flipped):
        frame = {"timestamp_ms": 33, "hands": hands}
        right_dominant = build_packet(frame, {}, cfg, "a", 0)
        left_dominant = build_packet(frame, {}, {**cfg, "dominant": "Left"}, "b", 0)
        assert right_dominant["hands"] == left_dominant["hands"]
        assert right_dominant["hands"]["Left"]["fingertips"][1]["xy"][0] < .5


def test_sender_hides_bad_points_without_clamping_or_inventing_depth():
    h = hand(.5, .5)
    h["image"][4][0] = float("nan")
    h["image"][8][0] = 1.2
    h["image"] = h["image"][:20]
    frame = {"timestamp_ms": 0, "hands": {"Right": h}}
    p = build_packet(frame, {}, {**config(), "interaction_version": 2}, "a", 0)
    tips = {t["finger_id"]: t for t in p["hands"]["Right"]["fingertips"]}
    for finger in ("thumb", "index", "pinky"):
        assert not tips[finger]["valid"] and tips[finger]["xy"] is None
    assert tips["middle"]["valid"] and tips["ring"]["valid"]
    assert not p["hands"]["Left"]["valid"]
    assert all(not t["valid"] for t in p["hands"]["Left"]["fingertips"])


def test_hover_pipeline_never_activates_operations_and_simulation_is_repeatable():
    cfg = {**config(), "interaction_version": 2}
    pipeline = Pipeline(cfg)
    frames, _ = demo_frames()
    for frame in frames:
        for sample, state in pipeline.step(frame):
            assert state["mode"] == "idle" and state["operation_id"] == 0
            p = build_packet(sample, state, cfg, "a", 0)
            assert p["profile"] == "hover2d" and "mode" not in p
    assert pipeline.controller.mode == "idle"
    assert hover_frames() == hover_frames()
    pipeline = Pipeline(cfg)
    counts = []
    for frame in hover_frames():
        for sample, state in pipeline.step(frame):
            p = build_packet(sample, state, cfg, "a", 0)
            counts.append(sum(t["valid"] for h in p["hands"].values() for t in h["fingertips"]))
    assert set(counts) == {5, 9, 10}
    assert counts[0] == counts[-1] == 10
    with pytest.raises(ValueError, match="does not run intent"):
        Pipeline(cfg, "gru")


def test_preview_config_is_opt_in():
    assert config()["interaction_version"] == 1
    assert config("configs/hover.json")["interaction_version"] == 2
