"""Verify the installed ZIP includes every hand style and licensed asset."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile
import bpy

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'dist/airclay_blender.zip'
OUTPUT=ROOT/'runs/smooth_hand'
OUTPUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='airclay-hand-package-') as directory:
    with zipfile.ZipFile(ARCHIVE) as archive:
        archive.extractall(directory)
        for p in (ROOT/'blender_addon/airclay_blender').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                assert archive.read('airclay_blender/'+str(p.relative_to(ROOT/'blender_addon/airclay_blender')))==p.read_bytes()
    sys.path.insert(0,directory)
    import airclay_blender as addon
    from airclay_blender.hand_display import HandDisplay
    assert str(Path(addon.__file__)).startswith(directory)
    addon.register()
    settings=bpy.context.scene.airclay
    assert settings.hand_model=='SMOOTH' and not settings.plastic_collision
    before=(len(bpy.data.images),len(bpy.data.materials),len(bpy.data.collections))
    display=HandDisplay(bpy.context.scene,{'Left':(0,0,1,1),'Right':(1,.5,0,1)})
    for mode,count in [('SMOOTH',14499),('REALISTIC',16330),('SIMPLE',None)]:
        settings.hand_model=mode
        display.set_style(settings)
        assert not settings.hand_model_status
        assert display.style==mode
        if count:
            assert len(display.skin.vertices)==count
            assert display.skin.deform(display.skin.rest_points).shape==(count,3)
        else:
            assert display.skin is None
        if mode=='REALISTIC':
            assert len(display.images)==2 and all(i.packed_file for i in display.images)
    display.close()
    assert before==(len(bpy.data.images),len(bpy.data.materials),len(bpy.data.collections))
    addon.unregister()
report={'passed':True,'all_three_models_load':True,'assets_and_code_match':True,'default_smooth':True,
        'physics_default_off':True,'cleanup_passed':True,'zip_sha256':hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()}
(OUTPUT/'package_test.json').write_text(json.dumps(report,indent=2))
print('AIRCLAY_HAND_PACKAGE_TEST',json.dumps(report))
