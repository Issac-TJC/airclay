"""Procedural tracked hands for pose inspection, not calibrated colliders.

One mesh per hand: joint spheres, finger segments and a solid palm. Mesh topology
is allocated once and only vertex positions are updated on Blender's main thread.
"""
import math
import bpy
from mathutils import Vector
from .hand_skin import ASSETS, HandSkin

CHAINS = ((0, 1, 2, 3, 4), (0, 5, 6, 7, 8), (0, 9, 10, 11, 12),
          (0, 13, 14, 15, 16), (0, 17, 18, 19, 20))
EDGES = tuple((a, b) for chain in CHAINS for a, b in zip(chain, chain[1:]))


def tip_guide_geometry(points):
    """Small yellow fingertip direction guides like the reference display."""
    vertices, faces = [], []
    scale = max((points[9] - points[0]).length, 1e-6)
    for tip in (4, 8, 12, 16, 20):
        direction = (points[tip] - points[tip - 1]).normalized()
        axis = Vector((0, 0, 1)) if abs(direction.z) < .9 else Vector((1, 0, 0))
        u = direction.cross(axis).normalized()
        v = direction.cross(u)
        base = len(vertices)
        for center in (points[tip], points[tip] + direction * scale * .16):
            for j in range(6):
                angle = j * math.tau / 6
                vertices.append(tuple(center + scale * .006 * (math.cos(angle) * u + math.sin(angle) * v)))
        for j in range(6):
            k = (j + 1) % 6
            faces.append((base + j, base + k, base + 6 + k, base + 6 + j))
        faces.extend((tuple(base + j for j in reversed(range(6))), tuple(base + 6 + j for j in range(6))))
    return vertices, faces


def make_tip_material():
    material = bpy.data.materials.new('AirClay yellow fingertip guides')
    material.diffuse_color = (.92, .72, .015, 1)
    material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = material.diffuse_color
    shader.inputs['Roughness'].default_value = .5
    shader.inputs['Emission Color'].default_value = material.diffuse_color
    shader.inputs['Emission Strength'].default_value = .25
    return material


def mesh_geometry(points):
    """Return a small, constant-topology robot-hand mesh at 21 joint positions."""
    vertices, faces = [], []
    palm_size = max((points[5] - points[17]).length, (points[9] - points[0]).length, .0001)
    radius = palm_size * .048
    segments = 8
    # Low-poly spheres avoid dozens of independent objects and update handlers.
    for point in points:
        base = len(vertices)
        vertices.append(tuple(point + Vector((0, 0, radius))))
        for ring in range(1, 4):
            phi = math.pi * ring / 4
            for j in range(segments):
                theta = math.tau * j / segments
                vertices.append(tuple(point + radius * Vector((math.sin(phi) * math.cos(theta),
                                                               math.sin(phi) * math.sin(theta), math.cos(phi)))))
        bottom = len(vertices)
        vertices.append(tuple(point - Vector((0, 0, radius))))
        for j in range(segments):
            nxt = (j + 1) % segments
            faces.append((base, base + 1 + j, base + 1 + nxt))
            for ring in range(2):
                a = base + 1 + ring * segments
                faces.append((a + j, a + segments + j, a + segments + nxt, a + nxt))
            faces.append((bottom, base + 17 + nxt, base + 17 + j))
    for a, b in EDGES:
        direction = points[b] - points[a]
        axis = direction.normalized() if direction.length > 1e-8 else Vector((0, 1, 0))
        reference = Vector((0, 0, 1)) if abs(axis.z) < .9 else Vector((1, 0, 0))
        u = axis.cross(reference).normalized()
        v = axis.cross(u).normalized()
        base = len(vertices)
        for point in (points[a], points[b]):
            for j in range(segments):
                angle = math.tau * j / segments
                vertices.append(tuple(point + radius * .8 * (u * math.cos(angle) + v * math.sin(angle))))
        for j in range(segments):
            nxt = (j + 1) % segments
            faces.append((base + j, base + nxt, base + segments + nxt, base + segments + j))
        faces.extend((tuple(base + j for j in reversed(range(segments))),
                      tuple(base + segments + j for j in range(segments))))
    # Extruded palm follows wrist and MCP joints. Thumb has its own articulated chain.
    normal = (points[5] - points[0]).cross(points[17] - points[0])
    normal = normal.normalized() if normal.length > 1e-8 else Vector((0, 0, 1))
    palm = (0, 5, 9, 13, 17)
    base = len(vertices)
    for sign in (-1, 1):
        vertices.extend(tuple(points[i] + normal * radius * .55 * sign) for i in palm)
    faces.extend((tuple(base + i for i in reversed(range(5))), tuple(base + 5 + i for i in range(5))))
    for i in range(5):
        j = (i + 1) % 5
        faces.append((base + i, base + j, base + 5 + j, base + 5 + i))
    return vertices, faces


def display_points(runtime, hand):
    """Project image joints onto view-aligned planes with hand-local z relief.

    Root plane is a user-set visual placement. Local z is wrist-relative and its
    display scale comes from palm size; none of this estimates camera root depth.
    """
    if not runtime.obj or not hand["valid"]:
        return None
    experiment = getattr(runtime, "plastic", None)
    corners = experiment.bounds if experiment else [runtime.obj.matrix_world @ Vector(c) for c in runtime.obj.bound_box]
    center = sum(corners, Vector()) / 8
    radius = max((p - center).length for p in corners)
    normal = runtime.rv.view_rotation @ Vector((0, 0, 1))
    depth = runtime.settings.plastic_depth if experiment else runtime.settings.hand_plane_offset
    plane = center + normal * radius * depth
    # Preserve out-of-image joints; the renderer clips them. Runtime.ray() checks
    # hover bounds, so use the same projection formula here without that clipping.
    from bpy_extras import view3d_utils

    def on_plane(xy, at):
        pixel = (xy[0] * runtime.region.width, (1 - xy[1]) * runtime.region.height)
        origin = view3d_utils.region_2d_to_origin_3d(runtime.region, runtime.rv, pixel)
        direction = view3d_utils.region_2d_to_vector_3d(runtime.region, runtime.rv, pixel)
        denom = direction.dot(normal)
        if abs(denom) < 1e-6:
            return None
        distance = (at - origin).dot(normal) / denom
        if runtime.rv.is_perspective and distance <= runtime.area.spaces.active.clip_start:
            return None
        return origin + direction * distance

    image, local = hand["image"], [Vector(p) for p in hand["local_world"]]
    wrist, middle = on_plane(image[0], plane), on_plane(image[9], plane)
    palm_m = (local[9] - local[0]).length
    if wrist is None or middle is None or palm_m < .005:
        return None
    scale = (middle - wrist).length / palm_m
    points = []
    for xy, p in zip(image, local):
        z = max(-radius * .35, min(radius * .35, (p.z - local[0].z) * scale))
        # The camera image is already mirrored. Reverse only the local depth
        # relief for a hand parallel to the user's, without swapping x or hands.
        if runtime.settings.flip_hand_depth:
            z = -z
        point = on_plane(xy, plane - normal * z)
        if point is None:
            return None
        points.append(point)
    return points


class HandDisplay:
    def __init__(self, scene, colors):
        self.collection = bpy.data.collections.new("AirClay tracked hands (preview)")
        scene.collection.children.link(self.collection)
        self.objects = {}
        self.materials = {}
        self.points = {}
        self.pinched = {"Left": False, "Right": False}
        self.colors = colors
        self.requested_style = None
        self.style = "SIMPLE"
        self.skin = None
        self.images = []
        self.guides = {}

    def set_style(self, settings):
        requested = settings.hand_model
        if requested == self.requested_style:
            return
        self.clear_meshes()
        self.requested_style = requested
        self.style = requested
        settings.hand_model_status = ""
        if requested in ("REALISTIC", "SMOOTH"):
            try:
                self.skin = HandSkin(ASSETS / 'hand_smooth.npz') if requested == 'SMOOTH' else HandSkin()
                for name in (("hand_basecolor.jpg", "hand_roughness.png") if requested == 'REALISTIC' else ()):
                    img = bpy.data.images.load(str(ASSETS / name), check_existing=False)
                    self.images.append(img)
                    img.pack()
                if self.images:
                    self.images[1].colorspace_settings.name = 'Non-Color'
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                self.clear_meshes()
                self.style = "SIMPLE"
                settings.hand_model_status = "Skin unavailable; using simple hands"
                print("AirClay hand asset:", exc)

    def material(self, side):
        material = bpy.data.materials.new(f"AirClay {side} hand material")
        material.diffuse_color = ((.20, .40, .95, 1) if self.style == 'SMOOTH' else
                                 self.colors[side] if not self.skin else (.58, .31, .21, 1))
        if self.skin:
            material.use_nodes = True
            nodes, links = material.node_tree.nodes, material.node_tree.links
            shader = nodes.get('Principled BSDF')
            shader.inputs['Roughness'].default_value = .58
            shader.inputs['Subsurface Weight'].default_value = .06
            shader.inputs['Specular IOR Level'].default_value = .25
            if self.style == 'SMOOTH':
                shader.inputs['Base Color'].default_value = material.diffuse_color
                shader.inputs['Roughness'].default_value = .34
                shader.inputs['Subsurface Weight'].default_value = .10
                shader.inputs['Coat Weight'].default_value = .18
                self.materials[side] = material
                return material
            color = nodes.new('ShaderNodeTexImage')
            color.image = self.images[0]
            links.new(color.outputs['Color'], shader.inputs['Base Color'])
            roughness = nodes.new('ShaderNodeTexImage')
            roughness.image = self.images[1]
            split = nodes.new('ShaderNodeSeparateColor')
            links.new(roughness.outputs['Color'], split.inputs['Color'])
            links.new(split.outputs['Green'], shader.inputs['Roughness'])
            nodes.active = color
        self.materials[side] = material
        return material

    def hide(self, side=None):
        for key in ((side,) if side else ("Left", "Right")):
            obj = self.objects.get(key)
            if obj:
                obj.hide_set(True)
                obj.hide_render = True
            if key in self.guides:
                self.guides[key].hide_set(True)
                self.guides[key].hide_render = True
            self.points.pop(key, None)
            self.pinched[key] = False

    def update_guides(self, side, points, enabled):
        if not enabled:
            if side in self.guides:
                self.guides[side].hide_set(True)
                self.guides[side].hide_render = True
            return
        vertices, faces = tip_guide_geometry(points)
        if side not in self.guides:
            mesh = bpy.data.meshes.new('AirClay fingertip directions')
            mesh.from_pydata(vertices, [], faces)
            obj = bpy.data.objects.new(f'AirClay {side} fingertip guides', mesh)
            obj['airclay_tracked_hand'] = side
            obj.hide_select = True
            obj.color = (.92, .72, .015, 1)
            if 'tips' not in self.materials:
                self.materials['tips'] = make_tip_material()
            mesh.materials.append(self.materials['tips'])
            self.collection.objects.link(obj)
            self.guides[side] = obj
        obj = self.guides[side]
        obj.data.vertices.foreach_set('co', [v for p in vertices for v in p])
        obj.data.update()
        obj.hide_set(False)
        obj.hide_render = False

    def update(self, runtime, hands):
        if not runtime.settings.show_tracked_hands:
            self.hide()
            return
        self.set_style(runtime.settings)
        for side in ("Left", "Right"):
            hand = hands[side]
            points = display_points(runtime, hand)
            if points is None:
                self.hide(side)
                continue
            if self.skin:
                vertices = self.skin.deform(points, side, runtime.settings.flip_hand_depth)
                reflected = (side == "Left") != runtime.settings.flip_hand_depth
                faces = self.skin.triangles[:, ::-1] if reflected else self.skin.triangles
            else:
                vertices, faces = mesh_geometry(points)
            if side not in self.objects:
                mesh = bpy.data.meshes.new(f"AirClay {side} tracked mesh")
                mesh.from_pydata(vertices, [], faces)
                mesh.update()
                obj = bpy.data.objects.new(f"AirClay {side} hand (preview)", mesh)
                obj["airclay_tracked_hand"] = side
                obj["calibrated_depth"] = False
                obj["hand_model"] = self.style
                if self.skin:
                    obj["asset_credit"] = "Rigged hand by Elena FF — CC BY-SA 4.0"
                    obj["skin_reflected"] = reflected
                    uv = mesh.uv_layers.new(name="UVMap")
                    uv.data.foreach_set('uv', self.skin.uv[faces.ravel()].ravel())
                obj.hide_select = True
                material = self.material(side)
                obj.color = material.diffuse_color if self.style == 'SMOOTH' else self.colors[side]
                mesh.materials.append(material)
                self.collection.objects.link(obj)
                self.objects[side] = obj
                for polygon in mesh.polygons:
                    polygon.use_smooth = True
            obj = self.objects[side]
            if self.skin and obj["skin_reflected"] != reflected:
                obj.data.flip_normals()
                obj["skin_reflected"] = reflected
            obj.data.vertices.foreach_set("co", vertices.ravel() if self.skin else [v for p in vertices for v in p])
            obj.data.update()
            obj.hide_set(False)
            obj.hide_render = False
            self.points[side] = points
            self.update_guides(side, points, self.style == 'SMOOTH' and runtime.settings.show_hand_tip_guides)
            local = [Vector(p) for p in hand["local_world"]]
            ratio = (local[4] - local[8]).length / max((local[9] - local[0]).length, 1e-5)
            if ratio < runtime.cfg.get("pinch_close", .30):
                self.pinched[side] = True
            elif ratio > runtime.cfg.get("pinch_open", .45):
                self.pinched[side] = False

    def clear_meshes(self):
        # Remove only the objects/data created by this receiver instance.
        for obj in (*self.objects.values(), *self.guides.values()):
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for material in self.materials.values():
            if material.users == 0:
                bpy.data.materials.remove(material)
        for img in self.images:
            if img.users == 0:
                bpy.data.images.remove(img)
        self.objects.clear()
        self.guides.clear()
        self.materials.clear()
        self.images.clear()
        self.skin = None
        self.points.clear()

    def close(self):
        self.clear_meshes()
        bpy.data.collections.remove(self.collection)
