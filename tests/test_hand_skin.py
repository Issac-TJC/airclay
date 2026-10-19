"""Asset skinning math without importing bpy or starting Blender."""
import importlib.util
from pathlib import Path
import json
import hashlib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hand_skin', ROOT / 'blender_addon/airclay_blender/hand_skin.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_rest_pose_and_similarity_transform():
    skin = module.HandSkin()
    np.testing.assert_allclose(skin.deform(skin.rest_points), skin.vertices, atol=3e-7)
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    translation = np.array([3, -2, 1])
    points = skin.rest_points @ rotation.T * 2 + translation
    expected = skin.vertices @ rotation.T * 2 + translation
    np.testing.assert_allclose(skin.deform(points), expected, atol=2e-6)


def test_anatomical_left_and_front_back_reflect_entire_skin():
    skin = module.HandSkin()
    for reflection, side, flip in [(np.array([-1, 1, 1]), 'Left', False),
                                    (np.array([1, 1, -1]), 'Right', True),
                                    (np.array([-1, 1, -1]), 'Left', True)]:
        np.testing.assert_allclose(skin.deform(skin.rest_points * reflection, side, flip),
                                   skin.vertices * reflection, atol=3e-7)


def test_finger_bend_deforms_skin_and_degenerate_pose_stays_finite():
    skin = module.HandSkin()
    points = skin.rest_points.copy()
    points[7:9, 0] += .15
    moved = np.linalg.norm(skin.deform(points) - skin.vertices, axis=1)
    assert moved.max() > .1
    # Wrist/palm vertices uninfluenced by the index finger remain in place.
    wrist = np.where(skin.joints == 0, skin.weights, 0).sum(axis=1) > .999999
    assert wrist.any()
    assert moved[wrist].max() < 1e-6
    assert np.isfinite(skin.deform(np.zeros((21, 3)))).all()


def test_vendored_asset_integrity_license_and_weights():
    skin = module.HandSkin()
    manifest = json.loads((module.ASSETS / 'hand_manifest.json').read_text())
    assert manifest['asset_license'] == 'CC-BY-SA-4.0'
    for name, digest in manifest['files_sha256'].items():
        assert hashlib.sha256((module.ASSETS / name).read_bytes()).hexdigest() == digest
    assert hashlib.sha256((ROOT / 'assets/realistic_hand/source.glb').read_bytes()).hexdigest() == manifest['source_sha256']
    assert skin.triangles.max() < len(skin.vertices)
    assert skin.joints.max() < len(skin.segments)
    np.testing.assert_allclose(skin.weights.sum(axis=1), 1, atol=1e-6)


def test_bone_roll_stays_continuous_through_ninety_degree_curl():
    frames=[]
    for degree in np.linspace(70,110,161):
        angle=np.deg2rad(degree)
        frame=module.aim_frame(np.eye(3), np.array([0,np.cos(angle),np.sin(angle)]))
        np.testing.assert_allclose(frame.T @ frame,np.eye(3),atol=1e-10)
        assert np.linalg.det(frame) > .999999
        frames.append(frame)
    assert np.linalg.norm(np.diff(frames,axis=0),axis=(1,2)).max() < .01


def test_smooth_hand_is_closed_welded_and_has_a_longer_wrist():
    source=module.HandSkin()
    skin=module.HandSkin(module.ASSETS/'hand_smooth.npz')
    assert len(skin.vertices)==14499 < len(source.vertices)
    edges=np.sort(np.concatenate([skin.triangles[:,[0,1]],skin.triangles[:,[1,2]],skin.triangles[:,[2,0]]]),axis=1)
    _,counts=np.unique(edges,axis=0,return_counts=True)
    assert np.all(counts==2)  # No cracks, open seam or nonmanifold edge.
    local=(skin.vertices-skin.rest_points[0])@skin.palm
    old=(source.vertices-source.rest_points[0])@source.palm
    assert local[:,1].min() < old[:,1].min()-.18
    # Wrist is one coherent root region, free of metacarpal flap weights.
    root_weights=np.where(skin.joints==0,skin.weights,0).sum(axis=1)
    assert root_weights[local[:,1]<-.05].min() > .99999
    np.testing.assert_allclose(skin.deform(skin.rest_points),skin.vertices,atol=3e-7)
    for reflection,side,flip in [(np.array([-1,1,1]),'Left',False),(np.array([1,1,-1]),'Right',True)]:
        np.testing.assert_allclose(skin.deform(skin.rest_points*reflection,side,flip),skin.vertices*reflection,atol=3e-7)
    manifest=json.loads((module.ASSETS/'smooth_manifest.json').read_text())
    assert hashlib.sha256((module.ASSETS/'hand_smooth.npz').read_bytes()).hexdigest()==manifest['hand_smooth_sha256']
