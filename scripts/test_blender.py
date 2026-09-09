"""Actual bpy mesh smoke test; launch using Blender --background --python."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"blender_addon")]
import bpy
import numpy as np
import airclay_blender as addon
from airclay_blender.geometry import surface_weights,deform
from mathutils import Vector
from mathutils.bvhtree import BVHTree

addon.register()
bpy.ops.airclay.create()
obj=bpy.context.scene.airclay.target
assert 9000<len(obj.data.vertices)<12000
base=addon.mesh_array(obj)
bvh=BVHTree.FromPolygons([v.co for v in obj.data.vertices],[p.vertices[:] for p in obj.data.polygons])
hit,normal,face,distance=bvh.ray_cast(Vector((0,-3,0)),Vector((0,1,0)))
assert hit is not None
weights=surface_weights(base,[e.vertices[:] for e in obj.data.edges],obj.data.polygons[face].vertices[:],np.array(hit),.25)
changed=deform(base,weights,[0,-.3,.2])
addon.set_mesh(obj,changed)
assert np.max(np.linalg.norm(addon.mesh_array(obj)-base,axis=1))>.2
assert np.count_nonzero(weights)>5
addon.set_mesh(obj,base)
np.testing.assert_allclose(addon.mesh_array(obj),base,atol=1e-6)
addon.set_mesh(obj,changed)
np.testing.assert_allclose(addon.mesh_array(obj),changed,atol=1e-6)
output=ROOT/"runs/blender_geometry_smoke.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(output))
addon.unregister()
print(f"AIRCLAY_BLENDER_TEST_OK vertices={len(base)} affected={np.count_nonzero(weights)} artifact={output}")
