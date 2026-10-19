"""Native Blender plasticity numerical test; run --background --python."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "blender_addon")]
import bpy
import numpy as np
from airclay_blender.plasticity import PlasticExperiment, coordinates

OUTPUT = ROOT / "runs/plasticity"
OUTPUT.mkdir(parents=True, exist_ok=True)
report = {"synthetic": True, "passed": False, "blender": bpy.app.version_string}
experiment = None
try:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=1)
    obj = bpy.context.object
    base = coordinates(obj.data).copy()
    original_scene, original_frame = bpy.context.scene, bpy.context.scene.frame_current
    counts = (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
    experiment = PlasticExperiment(obj, bpy.context.window)
    assert experiment.body.soft_body.plastic == 100
    assert experiment.modifier.type == "SOFT_BODY"
    assert len(experiment.rest) < 1100
    assert not obj.modifiers  # No simulation modifiers added to the display mesh.
    # A newly detected finger inside the clay cannot start a force impulse.
    experiment.step({("Left", "index"): ((0, 0, 0), .1)}, force=True)
    assert not experiment.armed and experiment.waiting
    np.testing.assert_array_equal(coordinates(obj.data), base)
    steps = experiment.steps
    experiment.step({}, force=True)
    assert experiment.steps == steps
    samples, measurements = [], []
    at_release = None
    for frame in range(1, 331):
        distance = 1.5 if frame < 10 else 1.5 - .7 * min(1, (frame - 10) / 50) if frame < 100 else .8 + .7 * min(1, (frame - 100) / 40)
        experiment.step({("Left", "index"): ((-distance, 0, 0), .35),
                         ("Right", "index"): ((distance, 0, 0), .35)}, force=True)
        samples.append(experiment.last_ms)
        actual = coordinates(obj.data)
        assert bpy.context.window.scene == original_scene and original_scene.frame_current == original_frame
        assert len(actual) == len(base) and np.isfinite(actual).all()
        if frame == 180:
            at_release = actual.copy()
        if frame in (1, 60, 100, 180, 299, 300, 301, 330):
            measurements.append({"frame": frame, "max_displacement": float(np.linalg.norm(actual - base, axis=1).max()),
                                 "width": float(np.ptp(actual[:, 0]))})
    final = coordinates(obj.data).copy()
    retained = float(np.linalg.norm(final - base, axis=1).max())
    report.update(retained_after_release=retained, measurements=measurements)
    assert retained > .1, "No permanent collision deformation"
    assert np.ptp(final[:, 0]) < np.ptp(base[:, 0]) - .1
    assert np.linalg.norm(final - at_release, axis=1).max() < .05, "Shape did not settle after release"
    assert experiment.rebases >= 2 and experiment.frame < 300
    report.update(native_collision_passed=True, retained_after_release=retained,
                  cache_rebases=experiment.rebases, solver_median_ms=float(np.median(samples)),
                  proxy_vertices=len(experiment.rest), display_vertices=len(base), timeline_unchanged=True,
                  inside_start_rejected=True, measurements=measurements)
    experiment.close()
    experiment = None
    assert counts == (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
    np.testing.assert_array_equal(coordinates(obj.data), final)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "native_plasticity.blend"))
    report.update(passed=True, cleanup_passed=True)
finally:
    if experiment:
        experiment.close()
    report["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [*ROOT.glob("blender_addon/**/*.py"), Path(__file__)]}
    (OUTPUT / "native_test.json").write_text(json.dumps(report, indent=2))
    print("AIRCLAY_NATIVE_PLASTICITY_TEST", json.dumps({k: v for k, v in report.items() if k != "source_sha256"}), flush=True)
