"""Real hand transport -> Blender Collision -> Plasticity -> toggle/undo tests."""
import hashlib
import json
import select
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "blender_addon")]
import bpy
import numpy as np
from mathutils import Quaternion, Vector
from bpy_extras import view3d_utils
import airclay_blender as addon
from airclay.config import config
from airclay.interaction.protocol import Sender

bpy.context.preferences.view.show_splash = False
OUTPUT = ROOT / "runs/plasticity"
OUTPUT.mkdir(parents=True, exist_ok=True)
state = {}
report = {"synthetic": True, "passed": False, "blender": bpy.app.version_string}


def send(distance):
    runtime = addon._runtime
    hands = {}
    for side, sign in (("Left", -1), ("Right", 1)):
        points = [Vector((sign * (distance + .8), -.65, 0))]
        for finger in range(5):
            tip = Vector((sign * distance, (finger - 2) * .12, 0))
            for j in range(1, 5):
                points.append(points[0].lerp(tip, j / 4))
        image = []
        for p in points:
            xy = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, p)
            image.append([xy.x / runtime.region.width, 1 - xy.y / runtime.region.height, 0])
        local = [tuple((p - points[0]) * .1) for p in points]
        hands[side] = {"valid": True, "image": image, "world": local}
    p = state["sender"].send({"timestamp_ms": time.monotonic() * 1000, "hands": hands}, {})
    assert select.select([runtime.sock], [], [], .2)[0]
    runtime.tick()
    assert runtime.gate.seq == p["seq"]
    runtime.update_plastic(force=True)


def finish(error=None):
    report.update(passed=error is None, error=error)
    report["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [*ROOT.glob("blender_addon/**/*.py"), Path(__file__)]}
    if state.get("sender"):
        state["sender"].close()
    if addon._runtime:
        addon._runtime.settings.running = False
    (OUTPUT / "gui_test.json").write_text(json.dumps(report, indent=2))
    print("AIRCLAY_PLASTICITY_GUI_TEST", json.dumps({k: v for k, v in report.items() if k != "source_sha256"}), flush=True)
    if "--quit" in sys.argv:
        bpy.ops.wm.quit_blender()


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
        rv = area.spaces.active.region_3d
        rv.view_rotation = Quaternion((1, 0, 0, 0))
        rv.view_distance = 5
        rv.view_perspective = "PERSP"
        bpy.context.scene.airclay.port = 8769
        bpy.ops.airclay.start()
    state["sender"] = Sender({**config("configs/hands.json"), "port": 8769})
    state["phase"] = "tests"


def tests():
    runtime = addon._runtime
    base = addon.mesh_array(runtime.obj).copy()
    original_scene, original_frame = runtime.window.scene, runtime.scene.frame_current
    assert runtime.settings.plastic_collision is False
    send(1.5)
    assert runtime.plastic is None
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), base)
    counts = (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
    runtime.settings.plastic_finger_size = 4
    runtime.settings.plastic_collision = True
    runtime.update_plastic(force=True)
    assert runtime.plastic is not None, runtime.settings.plastic_status
    samples = []
    for i in range(160):
        d = 1.5 - .8 * min(1, i / 60) if i < 95 else .7 + .8 * min(1, (i - 95) / 35)
        send(d)
        assert runtime.settings.plastic_collision, runtime.settings.plastic_status
        samples.append(runtime.plastic.last_ms)
        assert runtime.window.scene == original_scene and runtime.scene.frame_current == original_frame
    after = addon.mesh_array(runtime.obj).copy()
    displacement = float(np.linalg.norm(after - base, axis=1).max())
    assert displacement > .03, displacement
    assert len(runtime.plastic.colliders) == 10
    assert all(c.modifiers[0].type == "COLLISION" for c in runtime.plastic.colliders.values())
    # Loss freezes shape and removes collider participation, rather than hiding
    # a still-active collision object in the display scene.
    runtime.last_seen = time.monotonic() - .31
    runtime.tick()
    assert not runtime.plastic.armed
    assert all(c.location.length > 50 for c in runtime.plastic.colliders.values())
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), after)
    runtime.settings.plastic_collision = False
    runtime.update_plastic()
    assert runtime.plastic is None and len(addon._history) == 1
    assert counts == (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), after)
    bpy.ops.airclay.history(redo=False)
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), base)
    bpy.ops.airclay.history(redo=True)
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), after)
    # Cancel also removes the private solver and restores the starting snapshot.
    send(1.5)
    runtime.settings.plastic_collision = True
    runtime.update_plastic(force=True)
    for i in range(55):
        send(1.5 - .8 * min(1, i / 45))
    assert runtime.plastic is not None, runtime.settings.plastic_status
    bpy.ops.airclay.cancel_plastic()
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), after)
    assert not runtime.settings.plastic_collision and runtime.plastic is None
    assert len(addon._history) == 1
    assert counts == (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
    send(1.5)
    runtime.settings.plastic_collision = True
    runtime.update_plastic(force=True)
    assert runtime.plastic is not None
    saved_shape = addon.mesh_array(runtime.obj).copy()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "save_while_enabled.blend"))
    assert runtime.plastic is None and not runtime.settings.plastic_collision
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), saved_shape)
    assert counts == (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
    report.update(default_off=True, native_ten_tip_collision=True, retained_displacement=displacement,
                  toggle_off_keeps_shape=True, undo_redo_passed=True, cancel_passed=True,
                  loss_disables_colliders=True, cleanup_passed=True, timeline_unchanged=True,
                  save_stops_and_keeps_shape=True)
    report["solver_median_ms"] = float(np.median(samples))
    state["phase"] = "capture"


def step():
    try:
        if not state:
            setup()
            return .5
        with bpy.context.temp_override(**state["context"]):
            if state["phase"] == "tests":
                tests()
                return .1
            send(1.1)
            bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "plastic_hands.blend"))
            bpy.ops.screen.screenshot(filepath=str(OUTPUT / "plastic_hands.png"))
            finish()
    except Exception:
        finish(traceback.format_exc())
    return None


bpy.app.timers.register(step, first_interval=2)
