"""AirClay Blender UI. All scene changes are made by a main-thread modal timer."""
bl_info = {"name": "AirClay", "author": "AirClay course project", "version": (0, 1, 0),
           "blender": (5, 2, 0), "location": "3D View > Sidebar > AirClay", "category": "3D View"}

import json
import math
import socket
import time
from pathlib import Path

import bpy
import blf
import gpu
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree

try:
    from .protocol import PacketGate  # Standalone packaged add-on.
except ImportError:
    from airclay.interaction.protocol import PacketGate
from .geometry import surface_weights, deform

ROOT = Path(__file__).resolve().parents[2]
_runtime = None
_history = []
_redo = []


def mesh_array(obj):
    result = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", result)
    return result.reshape((-1, 3))


def set_mesh(obj, vertices):
    obj.data.vertices.foreach_set("co", np.asarray(vertices, dtype=np.float32).ravel())
    obj.data.update()


def view_snapshot(rv):
    return (rv.view_rotation.copy(), rv.view_location.copy(), rv.view_distance)


def restore_view(rv, snapshot):
    rv.view_rotation, rv.view_location, rv.view_distance = snapshot


class AirClaySettings(bpy.types.PropertyGroup):
    running: BoolProperty(default=False, options={"SKIP_SAVE"})
    status: StringProperty(default="Stopped", options={"SKIP_SAVE"})
    dominant: EnumProperty(items=[("Right", "Right", "Right hand sculpts"), ("Left", "Left", "Left hand sculpts")], default="Right")
    radius: FloatProperty(name="Brush radius", default=.25, min=.08, max=.60)
    port: IntProperty(name="Port", default=8765, min=1024, max=65535)
    target: PointerProperty(name="Clay mesh", type=bpy.types.Object, poll=lambda self, obj: obj.type == "MESH")


class AIRCLAY_OT_create(bpy.types.Operator):
    bl_idname = "airclay.create"
    bl_label = "Create clay sphere"
    bl_description = "Create a new sphere without deleting existing objects"

    def execute(self, context):
        if _runtime:
            _runtime.finish(False)
        if context.object and context.object.mode != "OBJECT":
            self.report({"ERROR"}, "Switch to Object Mode first")
            return {"CANCELLED"}
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=1)
        obj = context.object
        obj.name = "AirClay"
        for face in obj.data.polygons:
            face.use_smooth = True
        obj.color = (.55, .25, .10, 1)
        context.scene.airclay.target = obj
        _history.clear()
        _redo.clear()
        if context.area and context.area.type == "VIEW_3D":
            context.space_data.region_3d.view_location = obj.location
            context.space_data.region_3d.view_distance = 4
            context.space_data.shading.color_type = "OBJECT"
        return {"FINISHED"}


class Runtime:
    def __init__(self, context):
        self.scene = context.scene
        self.settings = context.scene.airclay
        self.area = context.area
        self.region = next(r for r in self.area.regions if r.type == "WINDOW")
        self.rv = context.space_data.region_3d
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(("127.0.0.1", self.settings.port))
        except Exception:
            self.sock.close()
            raise
        self.sock.setblocking(False)
        self.gate = PacketGate()
        self.last_seen = time.monotonic()
        self.packet = None
        self.active = None
        self.finished_key = None
        self.ready = False
        self.pointer = (.5, .5)
        self.mode = "idle"
        self.last_control = 0
        self.obj = self.settings.target
        self.bvh = None
        self.cfg = {"loss_ms": 300, "max_displacement": .5, "history_limit": 30,
                    "radius_min": .08, "radius_max": .60}
        config_path = ROOT / "configs/default.json"
        if config_path.exists():
            self.cfg.update(json.loads(config_path.read_text()))
        self.metrics = []
        self.rebuild()

    def rebuild(self):
        self.obj = self.settings.target
        if self.obj and self.obj.type == "MESH":
            self.bvh = BVHTree.FromPolygons([v.co for v in self.obj.data.vertices],
                                            [p.vertices[:] for p in self.obj.data.polygons])
        else:
            self.bvh = None

    def ray(self, pointer):
        xy = (pointer[0] * self.region.width, (1 - pointer[1]) * self.region.height)
        return (view3d_utils.region_2d_to_origin_3d(self.region, self.rv, xy),
                view3d_utils.region_2d_to_vector_3d(self.region, self.rv, xy))

    def hit(self, pointer):
        if self.bvh is None:
            return None
        origin, direction = self.ray(pointer)
        inv = self.obj.matrix_world.inverted()
        hit, normal, face, distance = self.bvh.ray_cast(inv @ origin, (inv.to_3x3() @ direction).normalized())
        return (hit, normal, face) if hit is not None else None

    def point_on_plane(self, pointer, point, normal):
        origin, direction = self.ray(pointer)
        denominator = direction.dot(normal)
        if abs(denominator) < 1e-6:
            return None
        return origin + direction * ((point - origin).dot(normal) / denominator)

    def snapshot(self):
        return {"object": self.obj, "vertices": mesh_array(self.obj),
                "view": view_snapshot(self.rv), "radius": self.settings.radius}

    def restore(self, snapshot):
        obj = snapshot["object"]
        if obj and len(obj.data.vertices) == len(snapshot["vertices"]):
            set_mesh(obj, snapshot["vertices"])
        restore_view(self.rv, snapshot["view"])
        self.settings.radius = snapshot["radius"]
        self.rebuild()

    def begin(self, packet):
        if not self.obj or self.obj.mode != "OBJECT":
            return
        mode = packet["mode"]
        dominant = packet["dominant"]
        auxiliary = "Left" if dominant == "Right" else "Right"
        hands = packet["hands"]
        required = [dominant] if mode == "sculpt" else [auxiliary] if mode == "orbit" else [dominant, auxiliary]
        if not all(hands[s]["valid"] for s in required):
            return
        key = (packet["session"], packet["operation_id"])
        self.finished_key = key  # A missed ray cannot begin later in the same gesture.
        self.rebuild()
        start = {"key": key, "mode": mode, "before": self.snapshot(),
                 "pointer": tuple(hands[dominant if mode == "sculpt" else auxiliary]["pointer"])}
        if mode == "sculpt":
            hit = self.hit(start["pointer"])
            if hit is None:
                return
            point, _, face = hit
            vertices = start["before"]["vertices"]
            world_vertices = np.array([self.obj.matrix_world @ Vector(v) for v in vertices])
            world_point = self.obj.matrix_world @ point
            start["weights"] = surface_weights(world_vertices, [e.vertices[:] for e in self.obj.data.edges],
                                                self.obj.data.polygons[face].vertices[:], np.array(world_point), self.settings.radius)
            start["plane_point"] = world_point
            start["normal"] = self.rv.view_rotation @ Vector((0, 0, 1))
            start["origin"] = self.point_on_plane(start["pointer"], world_point, start["normal"])
        if mode == "resize":
            start["distance"] = max(.02, math.dist(hands["Left"]["pointer"], hands["Right"]["pointer"]))
        self.active = start

    def update(self, packet):
        if not self.active or packet["paused"]:
            return
        a = self.active
        dominant = packet["dominant"]
        auxiliary = "Left" if dominant == "Right" else "Right"
        if a["mode"] == "sculpt":
            restore_view(self.rv, a["before"]["view"])
            self.settings.radius = a["before"]["radius"]
            point = self.point_on_plane(packet["hands"][dominant]["pointer"], a["plane_point"], a["normal"])
            if point is not None:
                world_delta = point - a["origin"]
                if world_delta.length > self.cfg["max_displacement"]:
                    world_delta = world_delta.normalized() * self.cfg["max_displacement"]
                delta = self.obj.matrix_world.inverted().to_3x3() @ world_delta
                set_mesh(self.obj, deform(a["before"]["vertices"], a["weights"], delta, float("inf")))
        elif a["mode"] == "orbit":
            p = packet["hands"][auxiliary]["pointer"]
            dx, dy = p[0] - a["pointer"][0], p[1] - a["pointer"][1]
            q = a["before"]["view"][0]
            self.rv.view_rotation = Quaternion((0, 0, 1), -dx * math.pi * 2) @ q @ Quaternion((1, 0, 0), dy * math.pi)
            self.rv.view_location = self.obj.matrix_world.translation
        elif a["mode"] == "resize":
            distance = math.dist(packet["hands"]["Left"]["pointer"], packet["hands"]["Right"]["pointer"])
            self.settings.radius = max(self.cfg["radius_min"], min(self.cfg["radius_max"], a["before"]["radius"] * distance / a["distance"]))

    def finish(self, commit):
        if not self.active:
            return
        a, self.active = self.active, None
        if commit:
            _history.append((a["before"], self.snapshot()))
            del _history[:-self.cfg["history_limit"]]
            _redo.clear()
        else:
            self.restore(a["before"])
        self.rebuild()

    def process(self, packet):
        old_session = self.gate.session
        if not self.gate.accept(packet):
            return
        if old_session != packet["session"]:
            self.finish(False)
            self.ready = False
            self.finished_key = None
        self.last_seen = time.monotonic()
        self.packet = packet
        key = (packet["session"], packet["operation_id"])
        if self.active and self.active["key"] != key:
            # No terminal state received for previous operation: conservative rollback.
            self.finish(False)
        if packet["mode"] == "idle":
            self.finish(packet["outcome"] == "commit")
            self.ready = True
        elif self.ready and self.active is None and key != self.finished_key and not packet["paused"]:
            self.begin(packet)
        self.update(packet)
        self.mode = packet["mode"]
        pointer_side = packet["dominant"]
        if packet["mode"] == "orbit":
            pointer_side = "Left" if pointer_side == "Right" else "Right"
        self.pointer = tuple(packet["hands"][pointer_side]["pointer"])
        if packet["mode"] == "resize":
            self.pointer = tuple((a+b)/2 for a,b in zip(packet["hands"]["Left"]["pointer"], packet["hands"]["Right"]["pointer"]))
        self.settings.status = "Paused: hand lost" if packet["paused"] else f"Connected | {self.mode}"
        received = time.monotonic() * 1000
        sent = packet.get("sent_ms", received)
        if isinstance(sent, (int, float)) and math.isfinite(sent):
            self.metrics.append({"seq": packet["seq"], "transport_apply_ms": max(0, received - sent),
                                 "capture_apply_ms": max(0, received - packet["timestamp_ms"])})
            if len(self.metrics) > 18000:
                del self.metrics[:1000]

    def tick(self):
        if self.settings.target != self.obj:
            self.finish(False)
            _history.clear()
            _redo.clear()
            self.rebuild()
        for _ in range(64):
            try:
                raw, address = self.sock.recvfrom(8192)
                packet = json.loads(raw)
                # Captured time is monotonic on this same machine.
                age = time.monotonic() * 1000 - packet.get("sent_ms", 0)
                if 0 <= age < self.cfg["loss_ms"]:
                    self.process(packet)
                if time.monotonic() - self.last_control > .2:
                    msg = {"type": "settings", "dominant": self.settings.dominant}
                    self.sock.sendto(json.dumps(msg).encode(), address)
                    self.last_control = time.monotonic()
            except BlockingIOError:
                break
            except (ValueError, KeyError, TypeError):
                continue
        if (time.monotonic() - self.last_seen) * 1000 > self.cfg["loss_ms"]:
            self.finish(False)
            self.ready = False
            self.settings.status = "Waiting for tracker (open hands to arm)"
        self.area.tag_redraw()

    def close(self):
        self.finish(False)
        self.sock.close()
        self.settings.running = False
        self.settings.status = "Stopped"
        folder = ROOT / "runs"
        if folder.is_dir() and self.metrics:
            (folder / "blender_latency.json").write_text(json.dumps(self.metrics))


def draw_overlay(runtime):
    if bpy.context.area != runtime.area:
        return
    colors = {"idle": (.5, .85, 1, 1), "sculpt": (1, .5, .15, 1), "orbit": (.65, .5, 1, 1), "resize": (.2, 1, .6, 1)}
    color = colors[runtime.mode]
    p = (runtime.pointer[0] * runtime.region.width, (1 - runtime.pointer[1]) * runtime.region.height)
    radius = 10
    # The ring is sized by projecting a world-space brush radius at the surface.
    center = None
    if runtime.active and runtime.active["mode"] == "sculpt":
        center = runtime.point_on_plane(runtime.pointer, runtime.active["plane_point"], runtime.active["normal"])
    elif runtime.active is None or runtime.mode == "resize":
        hit = runtime.hit(runtime.pointer)
        if hit:
            center = runtime.obj.matrix_world @ hit[0]
    if center is not None:
        right = runtime.rv.view_rotation @ Vector((1, 0, 0))
        edge = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, center + right * runtime.settings.radius)
        projected = view3d_utils.location_3d_to_region_2d(runtime.region, runtime.rv, center)
        if edge is not None and projected is not None:
            p, radius = projected, max(5, (edge - projected).length)
    coords = [(p[0] + math.cos(i * 2 * math.pi / 64) * radius,
               p[1] + math.sin(i * 2 * math.pi / 64) * radius) for i in range(65)]
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": coords})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    blf.position(0, 24, 45, 0)
    blf.size(0, 26)
    blf.color(0, *color)
    blf.draw(0, f"AirClay | {runtime.settings.status} | radius {runtime.settings.radius:.2f}")


class AIRCLAY_OT_start(bpy.types.Operator):
    bl_idname = "airclay.start"
    bl_label = "Start receiver"
    _timer = None
    _draw = None

    def execute(self, context):
        global _runtime
        if context.area.type != "VIEW_3D" or _runtime:
            return {"CANCELLED"}
        if not context.scene.airclay.target:
            self.report({"ERROR"}, "Create or choose a clay mesh first")
            return {"CANCELLED"}
        try:
            _runtime = Runtime(context)
        except OSError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        context.scene.airclay.running = True
        self._timer = context.window_manager.event_timer_add(1 / 60, window=context.window)
        self._draw = bpy.types.SpaceView3D.draw_handler_add(draw_overlay, (_runtime,), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        global _runtime
        if _runtime is None or not _runtime.settings.running:
            self.cancel(context)
            return {"CANCELLED"}
        if event.type == "ESC" and event.value == "PRESS":
            self.cancel(context)
            return {"CANCELLED"}
        if (event.ctrl or event.oskey) and event.type == "Z" and event.value == "PRESS":
            bpy.ops.airclay.history(redo=event.shift)
            return {"RUNNING_MODAL"}
        if event.type == "TIMER":
            try:
                _runtime.tick()
            except Exception as exc:
                self.report({"ERROR"}, f"AirClay stopped: {exc}")
                self.cancel(context)
                return {"CANCELLED"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        global _runtime
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._draw:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw, "WINDOW")
            self._draw = None
        if _runtime:
            _runtime.close()
            _runtime = None


class AIRCLAY_OT_stop(bpy.types.Operator):
    bl_idname = "airclay.stop"
    bl_label = "Stop receiver"

    def execute(self, context):
        context.scene.airclay.running = False
        return {"FINISHED"}


class AIRCLAY_OT_history(bpy.types.Operator):
    bl_idname = "airclay.history"
    bl_label = "Undo / redo AirClay"
    redo: BoolProperty(default=False)

    def execute(self, context):
        source, dest = (_redo, _history) if self.redo else (_history, _redo)
        if not _runtime:
            self.report({"INFO"}, "Start receiver to use AirClay history")
            return {"CANCELLED"}
        _runtime.finish(False)
        if not source:
            return {"CANCELLED"}
        item = source.pop()
        _runtime.restore(item[1 if self.redo else 0])
        dest.append(item)
        return {"FINISHED"}


class AIRCLAY_PT_panel(bpy.types.Panel):
    bl_label = "AirClay"
    bl_idname = "AIRCLAY_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AirClay"

    def draw(self, context):
        s, layout = context.scene.airclay, self.layout
        layout.label(text=s.status)
        layout.operator("airclay.create")
        layout.prop(s, "target")
        layout.prop(s, "dominant", text="Sculpt hand")
        layout.prop(s, "radius")
        row = layout.row()
        row.enabled = not s.running
        row.prop(s, "port")
        layout.operator("airclay.stop" if s.running else "airclay.start")
        row = layout.row(align=True)
        row.operator("airclay.history", text="Undo").redo = False
        row.operator("airclay.history", text="Redo").redo = True
        layout.label(text="One pinch: sculpt / orbit")
        layout.label(text="Two pinches: brush size")
        layout.label(text="Open hands between actions")


CLASSES = (AirClaySettings, AIRCLAY_OT_create, AIRCLAY_OT_start, AIRCLAY_OT_stop, AIRCLAY_OT_history, AIRCLAY_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.airclay = PointerProperty(type=AirClaySettings)


def unregister():
    global _runtime
    if _runtime:
        _runtime.close()
        _runtime = None
    del bpy.types.Scene.airclay
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
