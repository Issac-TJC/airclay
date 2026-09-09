import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/"dist/airclay_blender.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as archive:
    for path in (ROOT/"blender_addon/airclay_blender").glob("*.py"):
        archive.write(path,"airclay_blender/"+path.name)
    archive.write(ROOT/"src/airclay/interaction/protocol.py","airclay_blender/protocol.py")
print(out)
