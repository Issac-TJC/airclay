import copy
import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest
from airclay.config import config, ROOT
from airclay.data_tools.synthetic import hand, demo_frames
from airclay.data_tools.annotate import replace_interval
from airclay.data_tools.dataset import validate_split
from airclay.interaction.state import Controller
from airclay.interaction.protocol import PacketGate, validate
from airclay.learning.features import Features, Resampler, preprocess, FEATURE_DIM, STATIC_INDICES
from airclay.tracking.camera import HandMatcher


def frame(t, right=False, left=False, missing=()):
    return {"timestamp_ms": t, "dominant":"Right", "hands":{
        k:v for k,v in {"Right":hand(.6,.5,right), "Left":hand(.3,.5,left,"Left")}.items() if k not in missing}}


def test_combo_lock_release_and_rearm():
    c = Controller(config())
    c.step(frame(0))
    assert c.step(frame(100,True))["mode"] == "idle"
    assert c.step(frame(200,True,True))["mode"] == "idle"
    assert c.step(frame(310,True,True))["mode"] == "resize"
    s = c.step(frame(350,True,False))
    assert s["mode"] == "idle" and s["outcome"] == "commit"
    assert c.step(frame(700,True,False))["mode"] == "idle"
    c.step(frame(750))
    c.step(frame(800,True))
    assert c.step(frame(1010,True))["mode"] == "sculpt"
    assert c.step(frame(1100,True,True))["mode"] == "sculpt"


def test_loss_pauses_then_cancels_without_switching():
    c=Controller(config())
    c.step(frame(0)); c.step(frame(50,True)); c.step(frame(260,True))
    assert c.step(frame(300,missing=("Right",)))["paused"]
    assert c.step(frame(599,missing=("Right",)))["mode"] == "sculpt"
    s=c.step(frame(600,missing=("Right",)))
    assert s["mode"]=="idle" and s["outcome"]=="cancel"
    assert c.step(frame(700,True))["mode"]=="idle"


def test_learned_intent_release_debounce_and_mode_lock():
    c=Controller(config())
    c.step(frame(0),"idle")
    c.step(frame(50,True),"sculpt")
    assert c.step(frame(260,True),"sculpt")["mode"]=="sculpt"
    assert c.step(frame(300,True,True),"resize")["mode"]=="sculpt"
    assert c.step(frame(350),"idle")["mode"]=="sculpt"
    assert c.step(frame(410,True),"sculpt")["mode"]=="sculpt"
    c.step(frame(500),"idle")
    assert c.step(frame(601),"idle")["outcome"]=="commit"


def packet(session="a",seq=0):
    return {"version":1,"session":session,"seq":seq,"timestamp_ms":0.,"operation_id":1,
            "dominant":"Right","mode":"idle","paused":False,"outcome":None,
            "hands":{s:{"valid":True,"pointer":[.5,.5]} for s in ("Left","Right")}}


def test_protocol_duplicate_reorder_and_retired_session():
    g=PacketGate()
    assert g.accept(packet(seq=3))
    assert not g.accept(packet(seq=2))
    assert not g.accept(packet(seq=3))
    assert g.accept(packet("b",0))
    assert not g.accept(packet("a",99))
    p=packet(); p["hands"]["Right"]["pointer"][0]=float("nan")
    with pytest.raises(ValueError): validate(p)


def test_causal_resampling_and_gap_masks():
    r=Resampler(30)
    first=frame(0); second=frame(110,True)
    out=r.push(first)+r.push(second)
    # Frames before t=110 cannot see the newly closed hand.
    assert all(sample["hands"]["Right"]["image"]==first["hands"]["Right"]["image"] for sample in out)
    gap=r.push(frame(500))
    assert any(not sample["hands"] for sample in gap if sample["timestamp_ms"] < 500)


def test_online_and_offline_features_identical():
    frames,_=demo_frames()
    timed,x=preprocess(frames)
    live=Features()
    y=np.stack([live.step(f) for f in timed])
    np.testing.assert_array_equal(x,y)
    assert x.shape[1]==FEATURE_DIM and np.isfinite(x).all()
    assert len(STATIC_INDICES)==135
    assert np.allclose(Features().step(frame(0,missing=("Left","Right"))),0)


def test_hand_assignment_uses_motion_when_classifier_flips():
    m=HandMatcher(smoothing=1)
    m.update([hand(.25,.5,side="Left"),hand(.75,.5)],0)
    actual_left=hand(.26,.5,side="Right")
    actual_right=hand(.74,.5,side="Left")
    result=m.update([actual_right,actual_left],33)
    assert result["Left"]["image"][8][0]==pytest.approx(.26)


def test_annotation_replace_preserves_neighbour_intervals():
    original=[{"start_ms":0,"end_ms":1000,"label":"idle"}]
    s=replace_interval(original,200,600,"sculpt")
    assert [(x["start_ms"],x["end_ms"],x["label"]) for x in s]==[(0,200,"idle"),(200,600,"sculpt"),(600,1000,"idle")]


def test_subject_leak_is_rejected():
    with pytest.raises(ValueError,match="leaks"):
        validate_split({"subjects":{"train":["a"],"val":["a"],"test":["c"]},"recordings":{"train":[],"val":[],"test":[]}})


def test_deformation_stays_on_connected_surface_and_caps_displacement():
    spec=importlib.util.spec_from_file_location("geometry",ROOT/"blender_addon/airclay_blender/geometry.py")
    geometry=importlib.util.module_from_spec(spec); spec.loader.exec_module(geometry)
    vertices=np.array([[0,0,0],[.1,0,0],[.2,0,0],[0,0,.001]])
    weights=geometry.surface_weights(vertices,[(0,1),(1,2)],[0],np.zeros(3),.2)
    assert weights[0]==1 and weights[2]==0 and weights[3]==0
    result=geometry.deform(vertices,weights,[0,0,100])
    assert result[0,2]==pytest.approx(.5)
    np.testing.assert_array_equal(result[3],vertices[3])
    np.testing.assert_array_equal(geometry.deform(vertices,weights,[0,0,0]),vertices)
