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
    if type(result["interaction_version"]) is not int or result["interaction_version"] not in (1, 2):
        raise ValueError("interaction_version must be 1 (operations) or 2 (hover preview)")
    if not 0 < result["hover_radius_ratio"] <= .1:
        raise ValueError("hover_radius_ratio must be in (0, 0.1]")
    if result["preview_profile"] not in ("hover2d", "hand_preview"):
        raise ValueError("preview_profile must be hover2d or hand_preview")
    return result
