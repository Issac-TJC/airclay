"""Synthetic M1 integration test in a real Blender window, with localhost UDP.

Run Blender --factory-startup --python scripts/test_hover_gui.py -- --quit
Artifacts are isolated in runs/m1; no camera or previous run files are used.
"""
import copy
import hashlib
import json
import math
import select
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "blender_addon")]
import bpy
bpy.context.preferences.view.show_splash = False  # This process only; never save preferences.
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector
import airclay_blender as addon
from airclay.config import config
from airclay.data_tools.synthetic import hand
from airclay.interaction.protocol import FINGERTIPS, Sender, image_to_region

OUTPUT = ROOT / "runs/m1"
OUTPUT.mkdir(parents=True, exist_ok=True)
report = {"synthetic": True, "passed": False, "blender": bpy.app.version_string}
state = {}


def source_hashes():
    files = [*ROOT.glob("src/airclay/**/*.py"), *ROOT.glob("blender_addon/**/*.py"),
             ROOT / "configs/default.json", Path(__file__)]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def finish(error=None):
    report.update(passed=error is None, error=error, source_sha256=source_hashes())
    if state.get("sender"):
        state["sender"].close()
    if addon._runtime:
        addon._runtime.settings.running = False
    (OUTPUT / "hover_gui.json").write_text(json.dumps(report, indent=2))
    print("AIRCLAY_HOVER_TEST", json.dumps({k: v for k, v in report.items() if k != "source_sha256"}), flush=True)
    if "--quit" in sys.argv:
        bpy.ops.wm.quit_blender()


def deliver(hands, dominant="Right"):
    sender, runtime = state["sender"], addon._runtime
    sender.cfg["dominant"] = dominant
    p = sender.send({"timestamp_ms": time.monotonic() * 1000, "hands": hands},
                    {"mode": "sculpt", "operation_id": 999, "paused": False, "outcome": "commit"})
    # Sender deliberately receives an operation request; v2 must discard it.
    assert select.select([runtime.sock], [], [], .2)[0], "UDP packet did not arrive"
    runtime.tick()
    assert runtime.gate.session == p["session"] and runtime.gate.seq == p["seq"]
    report["max_packet_bytes"] = max(report.get("max_packet_bytes", 0),
                                     len(json.dumps(p, separators=(",", ":")).encode()))
    return p


def raw_delivery(p):
    state["sender"].sock.sendto(json.dumps(p).encode(), state["sender"].address)
    assert select.select([addon._runtime.sock], [], [], .2)[0], "UDP packet did not arrive"
    addon._runtime.tick()


def hover_count():
    return sum(c["state"] == "hover" for c in addon._runtime.cursors.values())


def known_hands():
    runtime = addon._runtime
    hands, expected = {}, {}
    # Known front-sphere points project to ten distinct pixels in both cameras.
    for side, y, offset in (("Left", .3, -.2), ("Right", -.3, .2)):
        h = hand(.5, .5, side=side)
        for i, (finger, landmark) in enumerate(FINGERTIPS.items()):
            x = offset + (i - 2) * .17
            point = Vector((x, y, math.sqrt(1 - x*x - y*y)))
            screen = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, point)
            assert screen is not None
            h["image"][landmark] = [screen.x / runtime.region.width, 1 - screen.y / runtime.region.height, 0]
            expected[side, finger] = point
        hands[side] = h
    return hands, expected


def setup():
    addon.register()
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    state["context"] = {"window": window, "area": area, "region": region}
    with bpy.context.temp_override(**state["context"]):
        bpy.ops.airclay.create()
        obj = bpy.context.scene.airclay.target
        for other in list(bpy.context.scene.objects):
            if other != obj:
                bpy.data.objects.remove(other, do_unlink=True)
        bpy.context.scene.airclay.port = 8767
        area.spaces.active.show_region_ui = True
        rv = area.spaces.active.region_3d
        rv.view_rotation = Quaternion((1, 0, 0, 0))
        rv.view_location = Vector((0, 0, 0))
        rv.view_distance = 4
        rv.view_perspective = "PERSP"
        bpy.ops.airclay.start()
    state["sender"] = Sender({**config(), "interaction_version": 2, "port": 8767})
    state["phase"] = "tests"


def run_tests():
    runtime = addon._runtime
    obj = runtime.obj
    before = addon.mesh_array(obj).copy()
    transform = obj.matrix_world.copy()
    view = addon.view_snapshot(runtime.rv)
    radius = runtime.settings.radius
    hands, expected = known_hands()
    p = deliver(hands)
    assert hover_count() == 10 and len(runtime.hover_markers()) == 10
    errors, surface_errors = [], []
    for key, c in runtime.cursors.items():
        projected = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, c["local_point"])
        errors.append((projected - Vector(image_to_region(c["xy"], runtime.region.width, runtime.region.height))).length)
        surface_errors.append((c["local_point"] - expected[key]).length)
        assert c["local_point"].z > 0  # The overlapping rear sphere is never selected.
    assert max(errors) < 2 and max(surface_errors) < .003
    report.update(ten_tip_projection_max_px=max(errors), surface_error_max=max(surface_errors),
                  first_visible_surface_passed=True)
    # Order is irrelevant. A missing ID clears only that finger immediately.
    unordered = copy.deepcopy(p)
    unordered["seq"] += 1
    unordered["sent_ms"] = time.monotonic() * 1000
    for h in unordered["hands"].values():
        h["fingertips"].reverse()
    raw_delivery(unordered)
    assert hover_count() == 10
    missing = copy.deepcopy(unordered)
    missing["seq"] += 1
    missing["sent_ms"] = time.monotonic() * 1000
    missing["hands"]["Left"]["fingertips"] = [t for t in missing["hands"]["Left"]["fingertips"] if t["finger_id"] != "middle"]
    raw_delivery(missing)
    assert hover_count() == 9 and runtime.cursors["Left", "middle"]["state"] == "hidden", {
        "count": hover_count(), "seq": runtime.gate.seq, "expected_seq": missing["seq"],
        "cursors": {str(k): v["state"] for k, v in runtime.cursors.items()}, "status": runtime.settings.status}
    state["sender"].seq = missing["seq"] + 1
    deliver(hands)
    assert hover_count() == 10
    # Changing dominant hand cannot move points or exchange identity colors.
    positions = {k: tuple(v["local_point"]) for k, v in runtime.cursors.items()}
    deliver(hands, "Left")
    assert positions == {k: tuple(v["local_point"]) for k, v in runtime.cursors.items()}
    runtime.settings.show_all_fingertips = False
    assert {(s, f) for s, f, _, _ in runtime.hover_markers()} == {("Left", "index"), ("Right", "index")}
    runtime.settings.show_hover = False
    assert runtime.hover_markers() == []
    runtime.settings.show_all_fingertips = runtime.settings.show_hover = True
    # Out-of-image, no surface hit, lost hand, then recovery.
    edge = copy.deepcopy(hands)
    edge["Right"]["image"][8] = [1.1, .5, 0]
    edge["Left"]["image"][4] = [.01, .01, 0]
    deliver(edge)
    assert hover_count() == 8
    deliver({"Right": hands["Right"]})
    assert hover_count() == 5
    deliver(hands)
    assert hover_count() == 10
    # Malformed/old/duplicate packets do not retire the active session or update state.
    seq = runtime.gate.seq
    for bad in ([], {"sent_ms": "bad"}):
        raw_delivery(bad)
        assert runtime.gate.seq == seq
    for change in ({"version": 99}, {"sent_ms": time.monotonic() * 1000 - 1000},
                   {"sent_ms": time.monotonic() * 1000 + 1000},
                   {"sent_ms": float("nan")}, {"mode": "sculpt"}):
        bad = copy.deepcopy(runtime.packet)
        bad.update(seq=seq + 1, **change)
        raw_delivery(bad)
        assert runtime.gate.seq == seq and hover_count() == 10
    raw_delivery(runtime.packet)
    assert runtime.gate.seq == seq
    report["snapshot_loss_order_and_identity_passed"] = True
    # Timeout hides all cursors; a complete fresh snapshot restores only present tips.
    runtime.last_seen = time.monotonic() - .31
    runtime.tick()
    assert hover_count() == 0 and runtime.packet is None
    old_packet = copy.deepcopy(p)
    state["sender"].close()
    state["sender"] = Sender({**config(), "interaction_version": 2, "port": 8767})
    deliver({"Right": hands["Right"]})
    assert hover_count() == 5
    old_packet.update(sent_ms=time.monotonic() * 1000, seq=9999)
    raw_delivery(old_packet)
    assert hover_count() == 5
    deliver(hands)
    assert hover_count() == 10
    report["timeout_reconnect_passed"] = True
    # Orthographic projection and a changed view must refresh candidate locations.
    runtime.rv.view_perspective = "ORTHO"
    runtime.rv.update()
    ortho_hands, _ = known_hands()
    deliver(ortho_hands)
    assert hover_count() == 10
    runtime.rv.view_rotation = Quaternion((0, 1, 0), math.pi / 4)
    runtime.rv.update()
    runtime.refresh_cursors()
    assert hover_count() == 10
    for c in runtime.cursors.values():
        projected = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, c["local_point"])
        assert (projected - Vector(image_to_region(c["xy"], runtime.region.width, runtime.region.height))).length < 2
    runtime.rv.view_perspective = "PERSP"
    addon.restore_view(runtime.rv, view)
    runtime.rv.update()
    deliver(hands)
    # A reversed first surface is hidden, rather than selecting a later face.
    original_bvh = runtime.bvh
    from mathutils.bvhtree import BVHTree
    runtime.bvh = BVHTree.FromPolygons([v.co for v in obj.data.vertices],
                                      [list(reversed(p.vertices[:])) for p in obj.data.polygons])
    runtime.refresh_cursors()
    assert hover_count() == 0
    runtime.bvh = original_bvh
    deliver(hands)
    np.testing.assert_array_equal(addon.mesh_array(obj), before)
    assert obj.matrix_world == transform and runtime.settings.radius == radius
    assert tuple(runtime.rv.view_rotation) == tuple(view[0])
    assert runtime.rv.view_location == view[1] and runtime.rv.view_distance == view[2]
    assert runtime.active is None and not runtime.ready and not addon._history and not addon._redo
    # A new preview session rolls back an in-flight v1 drag instead of committing.
    state["sender"].close()
    state["sender"] = Sender({**config(), "port": 8767})
    neutral = {"mode": "idle", "operation_id": 0, "paused": False, "outcome": None}
    for operation, dx in ((neutral, 0), ({**neutral, "mode": "sculpt", "operation_id": 1}, 0),
                          ({**neutral, "mode": "sculpt", "operation_id": 1}, .05)):
        v1_hands = {"Right": hand(.5 + dx, .5)}
        state["sender"].send({"timestamp_ms": time.monotonic() * 1000, "hands": v1_hands}, operation)
        assert select.select([runtime.sock], [], [], .2)[0]
        runtime.tick()
    assert np.linalg.norm(addon.mesh_array(obj) - before) > .01
    state["sender"].close()
    state["sender"] = Sender({**config(), "interaction_version": 2, "port": 8767})
    deliver(hands)
    np.testing.assert_array_equal(addon.mesh_array(obj), before)
    assert runtime.active is None and not runtime.ready and not addon._history
    report.update(preview_no_operations_passed=True, orthographic_and_view_change_passed=True,
                  reversed_first_surface_hidden=True, viewport_size=[runtime.region.width, runtime.region.height],
                  pixel_size=bpy.context.preferences.system.pixel_size, v1_to_preview_rollback_passed=True)
    state["hands"] = hands
    state["phase"] = "capture"


def step():
    try:
        if not state:
            setup()
            return .5
        with bpy.context.temp_override(**state["context"]):
            if state["phase"] == "tests":
                run_tests()
                return .1
            deliver(state["hands"])
            bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "hover_demo.blend"))
            bpy.ops.screen.screenshot(filepath=str(OUTPUT / "hover_preview.png"))
            finish()
    except Exception:
        finish(traceback.format_exc())
    return None


bpy.app.timers.register(step, first_interval=2)
