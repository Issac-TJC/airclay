"""Render the saved, actually deformed demo mesh; not an AI-generated mockup."""
from pathlib import Path
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
scene=bpy.context.scene
obj=next(o for o in scene.objects if o.type=="MESH" and o.name.startswith("AirClay"))
material=bpy.data.materials.new("AirClay warm clay")
material.diffuse_color=(.45,.18,.055,1)
material.use_nodes=True
principled=material.node_tree.nodes.get("Principled BSDF")
principled.inputs["Base Color"].default_value=(.45,.18,.055,1)
principled.inputs["Roughness"].default_value=.72
obj.data.materials.clear()
obj.data.materials.append(material)
rv=next(a.spaces.active.region_3d for a in bpy.context.screen.areas if a.type=="VIEW_3D")
bpy.ops.object.camera_add()
camera=bpy.context.object
camera.rotation_mode="QUATERNION"
camera.rotation_quaternion=rv.view_rotation
camera.location=rv.view_rotation@Vector((0,0,5.5))
camera.data.type="ORTHO"
camera.data.ortho_scale=3.4
scene.camera=camera
for name,local,energy,size in [("Key",(-3,-1,4),650,4),("Fill",(3,1,2),350,3),("Rim",(0,3,-1),450,2)]:
    data=bpy.data.lights.new(name,"AREA")
    light=bpy.data.objects.new(name,data)
    scene.collection.objects.link(light)
    light.location=rv.view_rotation@Vector(local)
    light.rotation_euler=(-light.location).to_track_quat("-Z","Y").to_euler()
    data.energy=energy; data.shape="DISK"; data.size=size
scene.world.color=(.18,.18,.18)
scene.render.engine="CYCLES"
scene.cycles.samples=32
scene.cycles.device="CPU"
scene.render.resolution_x=960
scene.render.resolution_y=960
scene.render.resolution_percentage=100
scene.render.image_settings.file_format="PNG"
scene.render.filepath=str(ROOT/"runs/airclay_demo.png")
scene.render.film_transparent=False
bpy.ops.render.render(write_still=True)
print("Rendered",scene.render.filepath)
