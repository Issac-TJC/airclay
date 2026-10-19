"""Render fitted hand poses in Blender, including the reference-style view."""
import json
import hashlib
import sys
from pathlib import Path
import numpy as np
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'blender_addon'), str(ROOT / 'src')]
from airclay_blender.hand_skin import HandSkin, ASSETS
from airclay_blender.hand_display import tip_guide_geometry, make_tip_material

OUTPUT = ROOT / 'runs/smooth_hand'
OUTPUT.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
skin = HandSkin(ASSETS / 'hand_smooth.npz')
canonical = (skin.rest_points - skin.rest_points[0]) @ skin.palm / skin.length


def pose(name):
    p = canonical.copy()
    if name == 'open':
        p[:, 2] *= .3
    if name == 'pinch':
        # Bend the index and bring the thumb toward its tip, preserving lengths.
        for base in (5,):
            for offset, angle in enumerate((.35, 1.0, 1.6), 1):
                length = np.linalg.norm(canonical[base+offset]-canonical[base+offset-1])
                p[base+offset] = p[base+offset-1] + np.array([0, np.cos(angle), np.sin(angle)])*length
        target = p[8] + np.array([.04, 0, 0])
        for offset in (1,2,3):
            p[1+offset] = p[1]*(1-offset/3)+target*(offset/3)
    if name == 'fist':
        for base in (5,9,13,17):
            for offset, angle in enumerate((1.1, 2.4, 3.0), 1):
                length=np.linalg.norm(canonical[base+offset]-canonical[base+offset-1])
                p[base+offset]=p[base+offset-1]+np.array([0,np.cos(angle),np.sin(angle)])*length
        p[2]=p[1]+np.array([-.14,.13,.12]);p[3]=p[2]+np.array([-.18,.04,.08]);p[4]=p[3]+np.array([-.22,-.02,.04])
    return p


material=bpy.data.materials.new('Soft blue hand')
material.diffuse_color=(.20,.40,.95,1)
material.use_nodes=True
bs=material.node_tree.nodes.get('Principled BSDF')
bs.inputs['Base Color'].default_value=material.diffuse_color
bs.inputs['Roughness'].default_value=.34
bs.inputs['Subsurface Weight'].default_value=.10
bs.inputs['Coat Weight'].default_value=.18
for column,name in enumerate(('open','pinch','fist')):
 for side,x in (('Left',-1.),('Right',1.)):
  p=pose(name)
  # Fingers point down as in the user's reference. Mirrored anatomy per side.
  p*=np.array([1 if side=='Left' else -1,-1,-1])
  p[:,0]+=x+(column-1)*4.2
  v=skin.deform(p,side,True)
  reflected=(side=='Left') != True
  f=skin.triangles[:,::-1] if reflected else skin.triangles
  mesh=bpy.data.meshes.new(name+side);mesh.from_pydata(v,[],f);mesh.update()
  obj=bpy.data.objects.new(name+' '+side,mesh);bpy.context.collection.objects.link(obj)
  mesh.materials.append(material)
  for face in mesh.polygons:face.use_smooth=True
  gv,gf=tip_guide_geometry([Vector(v) for v in p])
  gm=bpy.data.meshes.new('Guide mesh');gm.from_pydata(gv,[],gf)
  go=bpy.data.objects.new(name+' '+side+' guides',gm);bpy.context.collection.objects.link(go)
  gold=bpy.data.materials.get('AirClay yellow fingertip guides') or make_tip_material()
  gm.materials.append(gold)
scene=bpy.context.scene
scene.render.engine='CYCLES';scene.cycles.samples=32
scene.render.resolution_x=1900;scene.render.resolution_y=580;scene.render.resolution_percentage=100
scene.world=bpy.data.worlds.new('Reference neutral background')
scene.world.color=(.24,.24,.24)
bpy.ops.object.camera_add(location=(0,-.8,12))
cam=bpy.context.object;cam.rotation_euler=(0,0,0);cam.data.type='ORTHO';cam.data.ortho_scale=12.8;scene.camera=cam
for loc,power,size in [((-3,1,5),900,5),((4,-3,4),650,4),((0,4,2),500,3)]:
 bpy.ops.object.light_add(type='AREA',location=loc);l=bpy.context.object;l.data.energy=power;l.data.shape='DISK';l.data.size=size
 l.rotation_euler=(Vector((0,-.8,0))-l.location).to_track_quat('-Z','Y').to_euler()
scene.view_settings.view_transform='AgX'
scene.render.image_settings.file_format='PNG'
scene.render.filepath=str(OUTPUT/'pose_study.png')
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT/'pose_study.blend'))
bpy.ops.render.render(write_still=True)

# Reference-facing pair, with the same skinning and materials as the pose study.
for obj in scene.objects:
 if obj.type=='MESH' and not obj.name.startswith('open'):
  obj.hide_render=True
cam.location.x=-4.2;cam.data.ortho_scale=4.0
scene.render.resolution_x=1000;scene.render.resolution_y=800
scene.render.filepath=str(OUTPUT/'reference_pose.png')
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT/'reference_pose.blend'))
bpy.ops.render.render(write_still=True)
report={'poses':['open','pinch','fist'],'renderer':'Blender Cycles','synthetic':True,'asset_sha256':hashlib.sha256((ASSETS/'hand_smooth.npz').read_bytes()).hexdigest(),'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ASSETS.parent/'hand_skin.py',ASSETS.parent/'hand_display.py']}}
(OUTPUT/'render_manifest.json').write_text(json.dumps(report,indent=2))
