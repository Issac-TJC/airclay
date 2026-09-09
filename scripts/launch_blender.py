"""Run with Blender --python. Loads source without installing into user preferences."""
import sys
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "blender_addon")]
import airclay_blender
from airclay.config import config
airclay_blender.register()


def setup():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with bpy.context.temp_override(window=window,area=area,region=region):
                    bpy.ops.airclay.create()
                    cfg=config()
                    bpy.context.scene.airclay.dominant=cfg["dominant"]
                    bpy.context.scene.airclay.radius=cfg["radius"]
                    bpy.context.scene.airclay.port=cfg["port"]
                    area.spaces.active.show_region_ui = True
                    # Remove the factory cube/camera/light only in this fresh startup scene.
                    for obj in list(bpy.context.scene.objects):
                        if obj != bpy.context.scene.airclay.target:
                            bpy.data.objects.remove(obj,do_unlink=True)
                    bpy.ops.airclay.start()
                return None
    return .5

bpy.app.timers.register(setup,first_interval=1.)
