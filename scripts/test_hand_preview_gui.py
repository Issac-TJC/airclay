"""Full-skeleton preview with real Blender meshes and localhost transport."""
import hashlib
import json
import select
import sys
import time
import traceback
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "blender_addon")]
import bpy
import numpy as np
from mathutils import Quaternion, Vector
from bpy_extras import view3d_utils
import airclay_blender as addon
from airclay.config import config
from airclay.data_tools.synthetic import hand_preview_frames
from airclay.interaction.protocol import Sender

bpy.context.preferences.view.show_splash = False
REALISTIC = "--realistic" in sys.argv
SMOOTH = "--smooth" in sys.argv
SKINNED = REALISTIC or SMOOTH
MODEL = "SMOOTH" if SMOOTH else "REALISTIC" if REALISTIC else "SIMPLE"
VERTEX_COUNT = 14499 if SMOOTH else 16330
OUTPUT = ROOT / ("runs/smooth_hand" if SMOOTH else "runs/realistic_hand" if REALISTIC else "runs/hand_preview")
OUTPUT.mkdir(parents=True, exist_ok=True)
state = {}
report = {"synthetic": True, "passed": False, "blender": bpy.app.version_string}


def send(frame):
    runtime = addon._runtime
    p = state["sender"].send({**frame, "timestamp_ms": time.monotonic() * 1000}, {})
    assert select.select([runtime.sock], [], [], .2)[0]
    runtime.tick()
    assert runtime.gate.seq == p["seq"]
    return p


def finish(error=None):
    report.update(passed=error is None, error=error)
    files = [*ROOT.glob("src/airclay/**/*.py"), *ROOT.glob("blender_addon/**/*.py"), Path(__file__)]
    if SKINNED:
        files.extend((ROOT / 'blender_addon/airclay_blender/assets').iterdir())
    report["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if state.get("sender"):
        state["sender"].close()
    if addon._runtime:
        addon._runtime.settings.running = False
    (OUTPUT / "gui_test.json").write_text(json.dumps(report, indent=2))
    print("AIRCLAY_HAND_PREVIEW_TEST", json.dumps({k: v for k, v in report.items() if k != "source_sha256"}), flush=True)
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
        area.spaces.active.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
        area.spaces.active.region_3d.view_distance = 5
        area.spaces.active.region_3d.view_perspective = "PERSP"
        bpy.context.scene.airclay.port = 8768
        assert bpy.context.scene.airclay.hand_model == "SMOOTH"
        bpy.context.scene.airclay.hand_model = MODEL
        bpy.ops.airclay.start()
    state["sender"] = Sender({**config("configs/hands.json"), "port": 8768})
    state["frames"] = hand_preview_frames()
    state["phase"] = "tests"


def tests():
    runtime = addon._runtime
    before = addon.mesh_array(runtime.obj).copy()
    transform = runtime.obj.matrix_world.copy()
    view = addon.view_snapshot(runtime.rv)
    radius = runtime.settings.radius
    counts = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    images_before = len(bpy.data.images)
    p = send(state["frames"][0])
    display = runtime.hand_display
    assert len(display.objects) == 2 and len(display.points) == 2
    assert all(len(v) == 21 for v in display.points.values())
    assert not any(display.pinched.values())
    if SMOOTH:
        assert len(display.guides) == 2
        assert all(len(o.data.vertices) == 60 for o in display.guides.values())
        assert tuple(display.objects['Left'].color) == tuple(display.objects['Right'].color)
        runtime.settings.show_hand_tip_guides = False
        runtime.refresh_hands()
        assert all(o.hide_get() for o in display.guides.values())
        runtime.settings.show_hand_tip_guides = True
        runtime.refresh_hands()
        assert not any(o.hide_get() for o in display.guides.values())
    if SKINNED:
        assert display.skin is not None, runtime.settings.hand_model_status
        assert len(display.objects['Right'].data.vertices) == VERTEX_COUNT
        assert all(img.packed_file for img in display.images)
        assert all(len(o.data.uv_layers) == 1 for o in display.objects.values())
    errors = []
    for side, points in display.points.items():
        for point, xy in zip(points, p["hands"][side]["image"]):
            screen = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, point)
            errors.append((screen - Vector((xy[0] * runtime.region.width, (1 - xy[1]) * runtime.region.height))).length)
    assert max(errors) < 2
    identities = {s: o.as_pointer() for s, o in display.objects.items()}
    open_vertices = addon.mesh_array(display.objects["Right"]).copy()
    # Both thumbs approach their index fingers, and local depth bends the mesh.
    send(state["frames"][90])
    assert all(display.pinched.values())
    assert np.linalg.norm(addon.mesh_array(display.objects["Right"]) - open_vertices) > .01
    # Front/back changes signed view depth, not wrist placement, projected xy,
    # hand identity or the PINCH indication. Exercise a pose with nonzero local z.
    assert runtime.settings.flip_hand_depth is True
    parallel = {s: [v.copy() for v in pts] for s, pts in display.points.items()}
    runtime.settings.flip_hand_depth = False
    runtime.refresh_hands()
    normal = runtime.rv.view_rotation @ Vector((0, 0, 1))
    depth_changes = []
    for side, points in display.points.items():
        assert (points[0] - parallel[side][0]).length < 1e-5
        for a, b in zip(points, parallel[side]):
            da = (a - points[0]).dot(normal)
            db = (b - parallel[side][0]).dot(normal)
            assert abs(da + db) < 1e-5
            depth_changes.append(abs(da - db))
            pa = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, a)
            pb = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, b)
            assert (pa - pb).length < 2
    assert max(depth_changes) > .001
    assert all(display.pinched.values())
    assert identities == {s: o.as_pointer() for s, o in display.objects.items()}
    runtime.settings.flip_hand_depth = True
    runtime.refresh_hands()
    assert all(o.rigid_body is None and len(o.modifiers) == 0 for o in display.objects.values())
    samples = []
    for frame in state["frames"][100:115]:
        start = time.perf_counter()
        send(frame)
        samples.append((time.perf_counter() - start) * 1000)
    assert identities == {s: o.as_pointer() for s, o in display.objects.items()}
    send(state["frames"][180])
    assert display.objects["Left"].hide_get() and not display.objects["Right"].hide_get()
    if SMOOTH:
        assert display.guides['Left'].hide_get() and not display.guides['Right'].hide_get()
    send(state["frames"][0])
    assert not any(o.hide_get() for o in display.objects.values())
    runtime.settings.show_tracked_hands = False
    runtime.refresh_hands()
    assert all(o.hide_get() for o in display.objects.values())
    runtime.settings.show_tracked_hands = True
    runtime.refresh_hands()
    runtime.last_seen = time.monotonic() - .31
    runtime.tick()
    assert all(o.hide_get() for o in display.objects.values()) and not display.points
    send(state["frames"][90])
    assert all(display.pinched.values())
    np.testing.assert_array_equal(addon.mesh_array(runtime.obj), before)
    assert runtime.obj.matrix_world == transform and runtime.settings.radius == radius
    assert tuple(runtime.rv.view_rotation) == tuple(view[0])
    assert runtime.active is None and not addon._history
    # Cleanup uses references to its own objects, never deleting the target mesh.
    display.close()
    runtime.hand_display = None
    assert counts == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    assert len(bpy.data.images) == images_before
    send(state["frames"][90])
    if SKINNED:
        points_before = {s: np.array(p) for s, p in runtime.hand_display.points.items()}
        runtime.settings.hand_model = 'SIMPLE'
        runtime.refresh_hands()
        assert all(len(o.data.vertices) == 876 for o in runtime.hand_display.objects.values())
        assert len(bpy.data.images) == images_before
        runtime.settings.hand_model = MODEL
        runtime.refresh_hands()
        assert all(len(o.data.vertices) == VERTEX_COUNT for o in runtime.hand_display.objects.values())
        for side, points in runtime.hand_display.points.items():
            np.testing.assert_array_equal(points, points_before[side])
        for obj in runtime.hand_display.objects.values():
            actual_uv = np.array([loop.uv[:] for loop in obj.data.uv_layers.active.data])
            expected_uv = runtime.hand_display.skin.uv[[loop.vertex_index for loop in obj.data.loops]]
            np.testing.assert_allclose(actual_uv, expected_uv, atol=1e-7)
        # A missing/broken asset must leave the tracked simple hands usable.
        runtime.settings.hand_model = 'SIMPLE'
        runtime.refresh_hands()
        runtime.settings.hand_model = MODEL
        with patch('airclay_blender.hand_display.HandSkin', side_effect=FileNotFoundError('test missing asset')):
            runtime.refresh_hands()
        assert runtime.hand_display.style == 'SIMPLE'
        assert runtime.settings.hand_model_status
        assert all(len(o.data.vertices) == 876 for o in runtime.hand_display.objects.values())
        assert len(bpy.data.images) == images_before
        runtime.settings.hand_model = 'SIMPLE'
        runtime.refresh_hands()
        runtime.settings.hand_model = MODEL
        runtime.refresh_hands()
        assert runtime.hand_display.skin is not None and not runtime.settings.hand_model_status
        report.update(hand_model=MODEL, realistic_skin=REALISTIC, smooth_skin=SMOOTH, packed_textures=REALISTIC, model_switch_passed=True, image_cleanup_passed=True)
        report.update(uv_after_reflection_passed=True, missing_asset_fallback_passed=True)
        if SMOOTH:
            report.update(reference_blue_material=True, fingertip_guides_passed=True)
    report.update(joint_projection_max_px=max(errors), pinch_pose_passed=True, front_back_flip_passed=True,
                  meshes_reused=True, loss_timeout_and_recovery_passed=True,
                  target_unchanged=True, cleanup_passed=True,
                  vertices_per_hand=len(runtime.hand_display.objects["Right"].data.vertices),
                  send_apply_median_ms=float(np.median(samples)),
                  packet_bytes=len(json.dumps(p, separators=(",", ":")).encode()))
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
            send(state["frames"][90])
            if REALISTIC and state['phase'] == 'capture':
                bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'hands_solid.png'))
                addon._runtime.area.spaces.active.shading.color_type = 'TEXTURE'
                state['phase'] = 'texture_capture'
                return .2
            bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "hands.blend"))
            bpy.ops.screen.screenshot(filepath=str(OUTPUT / "hands.png"))
            finish()
    except Exception:
        finish(traceback.format_exc())
    return None


bpy.app.timers.register(step, first_interval=2)
