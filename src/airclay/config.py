import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLENDER = Path.home() / "Library/Application Support/Steam/steamapps/common/Blender/Blender.app/Contents/MacOS/Blender"


def config(path=None):
    result = json.loads((ROOT / "configs/default.json").read_text())
    if path:
        result.update(json.loads(Path(path).read_text()))
    if result["dominant"] not in ("Left", "Right"):
        raise ValueError("dominant must be Left or Right")
    if not 0 < result["pinch_close"] < result["pinch_open"]:
        raise ValueError("pinch thresholds must satisfy 0 < close < open")
    if result["host"] != "127.0.0.1":
        raise ValueError("AirClay only binds localhost")
    return result
