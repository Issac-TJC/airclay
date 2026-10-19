"""Opt-in native Soft Body + Collision experiment, isolated from the user's scene.

Blender computes every deformation. A barycentric displacement transfer preserves
the display mesh's topology while a bounded-resolution proxy runs the solver.
"""
from contextlib import contextmanager
import time

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

MAX_PROXY_VERTICES = 642
CACHE_FRAMES = 300
COLLIDER_KEYS = tuple((side, finger) for side in ("Left", "Right")
                      for finger in ("thumb", "index", "middle", "ring", "pinky"))


def coordinates(mesh):
    values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", values)
    return values.reshape((-1, 3))


def write_coordinates(mesh, values):
    mesh.vertices.foreach_set("co", np.asarray(values, dtype=np.float32).ravel())
    mesh.update()


def discard_saved_simulations():
    """Remove tagged solver scenes left in files from an interrupted experiment."""
    for scene in list(bpy.data.scenes):
        if not scene.get("airclay_plasticity_temporary"):
            continue
        for window in bpy.context.window_manager.windows:
            if window.scene == scene:
                replacement = next((s for s in bpy.data.scenes if not s.get("airclay_plasticity_temporary")), None)
                window.scene = replacement or bpy.data.scenes.new("Scene")
        for obj in list(scene.objects):
            if obj.get("airclay_physics_owned") and len(obj.users_scene) == 1:
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if mesh and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
        bpy.data.scenes.remove(scene)


class PlasticExperiment:
    def __init__(self, obj, window):
        if obj.mode != "OBJECT" or obj.data.shape_keys or obj.data.users != 1:
            raise ValueError("Plastic collision needs an Object Mode mesh without shape keys or shared mesh data")
        if len(obj.data.vertices) < 4 or not obj.data.polygons:
            raise ValueError("Plastic collision needs a surface mesh")
        if any(m.show_viewport for m in obj.modifiers):
            raise ValueError("Use a mesh without active modifiers for this plasticity experiment")
        self.obj, self.window = obj, window
        self.original = coordinates(obj.data).copy()
        self.center = (self.original.min(axis=0) + self.original.max(axis=0)) / 2
        self.radius = float(np.linalg.norm(self.original - self.center, axis=1).max())
        if not np.isfinite(self.original).all() or self.radius < 1e-5 or abs(obj.matrix_world.determinant()) < 1e-10:
            raise ValueError("Invalid or degenerate plasticity target")
        self.matrix = obj.matrix_world.copy()
        self.inverse = self.matrix.inverted()
        self.bounds = [self.matrix @ Vector(c) for c in obj.bound_box]
        self.scene = bpy.data.scenes.new("AirClay native plasticity (temporary)")
        self.scene["airclay_plasticity_temporary"] = True
        self.scene.gravity = (0, 0, 0)
        self.scene.render.fps = 30
        self.scene.frame_end = CACHE_FRAMES
        self.layer = self.scene.view_layers[0]
        self.colliders = {}
        self.armed = set()
        self.previous = {}
        self.last_ms = 0.
        self.last_step = 0.
        self.frame = 1
        self.steps = 0
        self.rebases = 0
        self.last_positions = self.original.copy()
        self.waiting = False
        self.needs_rebase = False
        self.closed = False
        try:
            mesh = bpy.data.meshes.new("AirClay physics proxy")
            mesh.from_pydata(((self.original - self.center) / self.radius).tolist(), [],
                             [p.vertices[:] for p in obj.data.polygons])
            self.body = bpy.data.objects.new("AirClay native soft body", mesh)
            self.body["airclay_physics_owned"] = True
            self.scene.collection.objects.link(self.body)
            with self.context():
                if len(mesh.vertices) > MAX_PROXY_VERTICES:
                    decimate = self.body.modifiers.new("Temporary proxy reduction", "DECIMATE")
                    decimate.ratio = MAX_PROXY_VERTICES / len(mesh.vertices)
                    self.layer.update()
                    graph = self.layer.depsgraph
                    evaluated = self.body.evaluated_get(graph)
                    reduced = bpy.data.meshes.new_from_object(evaluated, depsgraph=graph)
                    self.body.modifiers.remove(decimate)
                    self.body.data = reduced
                    bpy.data.meshes.remove(mesh)
                    mesh = reduced
                bm = bmesh.new()
                bm.from_mesh(mesh)
                bmesh.ops.triangulate(bm, faces=list(bm.faces))
                bm.to_mesh(mesh)
                bm.free()
                mesh.update()
                self.rest = coordinates(mesh).copy()
                self.current = self.rest.copy()
                self.faces = np.asarray([p.vertices[:] for p in mesh.polygons], dtype=np.int32)
                self._bind_display()
                # Creating collider objects after frame 1 invalidates Blender's
                # dependency graph/cache. Keep all ten slots for the whole run.
                for key in COLLIDER_KEYS:
                    self._collider(key)
                self._new_solver()
                self.scene.frame_set(1)
                self.layer.depsgraph.update()
        except Exception:
            self.close()
            raise

    @contextmanager
    def context(self):
        # Blender skips soft-body cache simulation for an inactive scene graph.
        # Activate only during this main-thread evaluation, restore before drawing.
        original_scene, original_layer = self.window.scene, self.window.view_layer
        try:
            self.window.scene = self.scene
            with bpy.context.temp_override(window=self.window, scene=self.scene, view_layer=self.layer):
                yield
        finally:
            self.window.scene = original_scene
            self.window.view_layer = original_layer

    def _new_solver(self):
        self.modifier = self.body.modifiers.new("AirClay native Plasticity", "SOFT_BODY")
        s = self.body.soft_body
        s.use_goal = False
        s.use_edges = True
        s.pull = .7
        s.push = .7
        s.damping = 10
        s.bend = 1
        s.plastic = 100
        s.friction = 5
        s.use_edge_collision = True
        s.use_self_collision = False
        s.effector_weights.gravity = 0
        s.step_min = 5
        s.step_max = 20
        self.modifier.point_cache.frame_start = 1
        self.modifier.point_cache.frame_end = CACHE_FRAMES
        self.modifier.point_cache.use_disk_cache = False

    def _surface(self):
        return BVHTree.FromPolygons(self.current.tolist(), self.faces.tolist(), all_triangles=True)

    def _bind_display(self):
        surface = self._surface()
        high = (self.original - self.center) / self.radius
        ids, weights = [], []
        for point in high:
            nearest, _, face, _ = surface.find_nearest(Vector(point))
            if nearest is None:
                raise ValueError("Could not bind display mesh to soft-body proxy")
            indices = self.faces[face]
            a, b, c = self.rest[indices].astype(np.float64)
            v0, v1, v2 = b - a, c - a, np.asarray(nearest) - a
            d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
            denominator = d00 * d11 - d01 * d01
            if abs(denominator) < 1e-16:
                weight = [1., 0., 0.]
            else:
                v = (d11 * (v2 @ v0) - d01 * (v2 @ v1)) / denominator
                w = (d00 * (v2 @ v1) - d01 * (v2 @ v0)) / denominator
                weight = [1 - v - w, v, w]
            ids.append(indices)
            weights.append(weight)
        self.indices = np.asarray(ids)
        self.weights = np.asarray(weights, dtype=np.float32)

    def _collider(self, key):
        if key not in self.colliders:
            mesh = bpy.data.meshes.new("AirClay fingertip collision sphere")
            bm = bmesh.new()
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1)
            bm.to_mesh(mesh)
            bm.free()
            obj = bpy.data.objects.new("AirClay collider " + str(key), mesh)
            obj["airclay_physics_owned"] = True
            self.scene.collection.objects.link(obj)
            obj.modifiers.new("Native Collision", "COLLISION")
            obj.location = (100, 100, 100)
            # Keep native collision relations stable. Inactive tips are parked
            # far outside this isolated scene, never toggled out of the graph.
            obj.collision.use = True
            obj.collision.thickness_outer = .01
            obj.collision.thickness_inner = .02
            obj.collision.damping = .8
            self.colliders[key] = obj
        return self.colliders[key]

    def disarm(self):
        self.needs_rebase = self.needs_rebase or bool(self.armed)
        self.armed.clear()
        self.previous.clear()
        for collider in self.colliders.values():
            collider.location = (100, 100, 100)

    def _rebase(self):
        # Bound the native point cache. The next solve starts from the current
        # deformed shape; the original display binding remains unchanged.
        self.body.modifiers.remove(self.modifier)
        write_coordinates(self.body.data, self.current)
        self._new_solver()
        self.frame = 1
        self.scene.frame_set(1)
        self.layer.depsgraph.update()
        self.rebases += 1
        self.needs_rebase = False

    def step(self, spheres, force=False):
        """spheres: stable ID -> (world-space center, world-space radius).

        New/lost/jumping tips cannot teleport into the clay; they must first be
        observed outside the current surface. No camera depth is inferred here.
        """
        now = time.monotonic()
        if not force and now - self.last_step < 1 / 30:
            return False
        self.last_step = now
        if not spheres:
            self.disarm()
            return False
        if not set(spheres).issubset(self.colliders):
            raise ValueError("Unknown fingertip collision ID")
        if self.obj.matrix_world != self.matrix or len(self.obj.data.vertices) != len(self.original):
            raise ValueError("Target changed; turn plastic collision off before editing its transform or topology")
        self.waiting = False
        started = time.perf_counter()
        surface = self._surface()
        world_to_local = max((self.inverse.to_3x3() @ Vector(axis)).length
                             for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
        with self.context():
            old_armed = set(self.armed)
            for key in set(self.colliders) - set(spheres):
                self.colliders[key].location = (100, 100, 100)
                self.armed.discard(key)
                self.previous.pop(key, None)
            for key, (world_point, world_radius) in spheres.items():
                point = (self.inverse @ Vector(world_point) - Vector(self.center)) / self.radius
                radius = max(.005, min(.5, world_radius * world_to_local / self.radius))
                collider = self._collider(key)
                previous = self.previous.get(key)
                if previous is not None and (point - previous).length > .25:
                    self.armed.discard(key)
                self.previous[key] = point.copy()
                if key not in self.armed:
                    nearest, normal, _, _ = surface.find_nearest(point)
                    if nearest is not None and (point - nearest).dot(normal) > radius + .02:
                        self.armed.add(key)
                    else:
                        self.waiting = True
                collider.location = point if key in self.armed else Vector((100, 100, 100))
                collider.scale = (radius,) * 3
            if self.frame >= CACHE_FRAMES or self.needs_rebase or self.armed != old_armed:
                # Reinitialize collision motion when participation changes, so
                # parking/reacquisition never sweeps a collider through the clay.
                self._rebase()
            self.frame += 1
            self.scene.frame_set(self.frame)
            graph = self.layer.depsgraph
            graph.update()
            result = coordinates(self.body.evaluated_get(graph).data)
            if (not np.isfinite(result).all() or np.max(np.linalg.norm(result - self.current, axis=1)) > .2
                    or np.max(np.linalg.norm(result - self.rest, axis=1)) > 2.):
                raise ValueError("Plastic solver motion exceeded limits; last stable shape kept. Reposition hands and re-enable")
            self.current = result.copy()
        deltas = ((self.current[self.indices] - self.rest[self.indices]) * self.weights[:, :, None]).sum(axis=1)
        self.last_positions = self.original + deltas * self.radius
        write_coordinates(self.obj.data, self.last_positions)
        self.steps += 1
        self.last_ms = (time.perf_counter() - started) * 1000
        return True

    def close(self):
        if self.closed:
            return
        self.closed = True
        for obj in list(self.scene.objects):
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.data.scenes.remove(self.scene)
