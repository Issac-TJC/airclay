"""Blender GUI integration test using the actual localhost receiver, no camera.

Creates its own scene and port. Leaves the saved demo open for visual inspection.
"""
import json
import sys
import time
import traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"blender_addon")]
import bpy
import numpy as np
from bpy_extras import view3d_utils
import airclay_blender as addon
from airclay.config import config
from airclay.data_tools.synthetic import demo_frames, hand
from airclay.interaction.state import Controller
from airclay.interaction.protocol import Sender

addon.register()
cfg=config(); cfg["port"]=8766
frames,_=demo_frames()
state={"index":0,"start":None,"phase":"init"}
report={"synthetic":True,"passed":False}


def finish(error=None):
    report["error"]=error
    report["passed"]=error is None
    if state.get("sender"):
        state["sender"].close()
    if addon._runtime:
        addon._runtime.settings.running=False
    (ROOT/"runs/gui_test.json").write_text(json.dumps(report,indent=2))
    print("AIRCLAY_GUI_TEST",json.dumps(report),flush=True)


def step():
    try:
        return run()
    except Exception:
        finish(traceback.format_exc())
        return None


def run():
    if state["phase"]=="init":
        window=bpy.context.window_manager.windows[0]
        area=next(a for a in window.screen.areas if a.type=="VIEW_3D")
        region=next(r for r in area.regions if r.type=="WINDOW")
        state["context"]={"window":window,"area":area,"region":region}
        with bpy.context.temp_override(**state["context"]):
            bpy.ops.airclay.create()
            obj=bpy.context.scene.airclay.target
            for other in list(bpy.context.scene.objects):
                if other != obj:
                    bpy.data.objects.remove(other,do_unlink=True)
            bpy.context.scene.airclay.port=cfg["port"]
            area.spaces.active.show_region_ui=True
            bpy.ops.airclay.start()
        state["before"]=addon.mesh_array(obj)
        state["view"]=tuple(addon._runtime.rv.view_rotation)
        state["sender"],state["controller"]=Sender(cfg),Controller(cfg)
        state["start"]=time.monotonic()
        state["phase"]="demo"
        return 1/30
    if state["phase"]=="demo":
        i=state["index"]
        if i<len(frames):
            frame={**frames[i],"timestamp_ms":time.monotonic()*1000}
            state["sender"].send(frame,state["controller"].step(frame))
            state["index"]+=1
            return 1/30
        state["phase"]="check"
        return .15
    if state["phase"]=="check":
        runtime=addon._runtime
        obj=runtime.obj
        report["vertices"]=len(obj.data.vertices)
        report["committed_operations"]=len(addon._history)
        report["max_vertex_displacement"]=float(np.linalg.norm(addon.mesh_array(obj)-state["before"],axis=1).max())
        assert len(addon._history)==4, f"Expected two sculpt/orbit/resize, got {len(addon._history)}"
        assert report["max_vertex_displacement"]>.15
        assert tuple(runtime.rv.view_rotation)!=state["view"]
        after_radius=runtime.settings.radius
        assert after_radius>.3
        with bpy.context.temp_override(**state["context"]):
            bpy.ops.airclay.history(redo=False)
            assert runtime.settings.radius<after_radius
            bpy.ops.airclay.history(redo=True)
            assert abs(runtime.settings.radius-after_radius)<1e-5
        report["undo_redo_passed"]=True
        report["brush_radius"]=after_radius
        hit=runtime.hit((.5,.5))
        assert hit is not None
        screen=view3d_utils.location_3d_to_region_2d(runtime.region,runtime.rv,obj.matrix_world@hit[0])
        assert abs(screen.x-runtime.region.width*.5)<1 and abs(screen.y-runtime.region.height*.5)<1
        report["ray_projection_passed"]=True
        # New session + neutral arms the receiver, then deliberately drop a drag.
        state["sender"].close()
        state["sender"]=Sender(cfg)
        state["cancel_base"]=addon.mesh_array(obj)
        state["phase"]="loss_neutral"
        return .05
    hands={"Left":hand(.3,.5,False,"Left"),"Right":hand(.5,.5,False)}
    frame={"timestamp_ms":time.monotonic()*1000,"hands":hands}
    packet_state={"mode":"idle","operation_id":0,"paused":False,"outcome":None}
    if state["phase"]=="loss_neutral":
        state["sender"].send(frame,packet_state)
        state["phase"]="loss_start"
        return .05
    if state["phase"]=="loss_start":
        packet_state.update(mode="sculpt",operation_id=1)
        state["sender"].send(frame,packet_state)
        state["phase"]="loss_move"
        return .05
    if state["phase"]=="loss_move":
        frame["hands"]["Right"]=hand(.55,.45,True)
        packet_state.update(mode="sculpt",operation_id=1)
        state["sender"].send(frame,packet_state)
        state["phase"]="loss_assert_move"
        return .1
    if state["phase"]=="loss_assert_move":
        assert np.linalg.norm(addon.mesh_array(addon._runtime.obj)-state["cancel_base"])>.01
        state["phase"]="loss_assert_restore"
        return .4
    if state["phase"]=="loss_assert_restore":
        runtime=addon._runtime
        np.testing.assert_allclose(addon.mesh_array(runtime.obj),state["cancel_base"],atol=1e-6)
        report["timeout_rollback_passed"]=True
        report["transport_apply_ms_median"]=float(np.median([r["transport_apply_ms"] for r in runtime.metrics]))
        report["elapsed_seconds"]=time.monotonic()-state["start"]
        with bpy.context.temp_override(**state["context"]):
            bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"runs/airclay_demo.blend"))
        finish()
        return None

bpy.app.timers.register(step,first_interval=2)
