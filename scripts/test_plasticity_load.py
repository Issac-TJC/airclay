"""Default-off on .blend load, including cleanup of interrupted solver scenes."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "blender_addon")]
import bpy
import numpy as np
import airclay_blender as addon
from airclay_blender.plasticity import PlasticExperiment, coordinates

OUTPUT = ROOT / "runs/plasticity"
OUTPUT.mkdir(parents=True, exist_ok=True)
addon.register()
bpy.ops.airclay.create()
obj = bpy.context.scene.airclay.target
name = obj.name
before = coordinates(obj.data).copy()
counts = (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
# Emulate a file made by an interrupted run: saved opt-in plus solver helpers.
# There is deliberately no live Runtime for the save-pre handler to finish.
experiment = PlasticExperiment(obj, bpy.context.window)
bpy.context.scene.airclay.plastic_collision = True
bpy.context.scene.airclay.running = True
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "interrupted_test.blend"))
assert bpy.context.scene.airclay.plastic_collision
bpy.ops.wm.open_mainfile(filepath=str(OUTPUT / "interrupted_test.blend"))
assert not bpy.context.scene.airclay.plastic_collision
assert not bpy.context.scene.airclay.running
assert not any(s.get("airclay_plasticity_temporary") for s in bpy.data.scenes)
assert counts == (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.meshes))
np.testing.assert_array_equal(coordinates(bpy.data.objects[name].data), before)
report = {"passed": True, "default_off_after_load": True, "orphan_solver_cleanup": True,
          "saved_mesh_preserved": True, "blender": bpy.app.version_string}
(OUTPUT / "load_test.json").write_text(json.dumps(report, indent=2))
print("AIRCLAY_PLASTICITY_LOAD_TEST", json.dumps(report), flush=True)
addon.unregister()
