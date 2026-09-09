import hashlib
import json
from pathlib import Path
import ssl
import urllib.request
import certifi

ROOT = Path(__file__).resolve().parents[1]
URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
target = ROOT / "assets/hand_landmarker.task"
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    with urllib.request.urlopen(URL, context=ssl.create_default_context(cafile=certifi.where()), timeout=60) as response:
        data = response.read()
    temporary = target.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.replace(target)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
manifest = {"url": URL, "sha256": digest, "bytes": target.stat().st_size,
            "documentation": "https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker"}
existing = ROOT / "assets/model_manifest.json"
if existing.exists() and json.loads(existing.read_text())["sha256"] != digest:
    raise RuntimeError("Model checksum differs from recorded manifest")
existing.write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2))
