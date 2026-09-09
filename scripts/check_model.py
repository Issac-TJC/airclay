"""Check the actual native MediaPipe runtime without opening a camera."""
import json
from pathlib import Path
import numpy as np
import mediapipe as mp

ROOT=Path(__file__).resolve().parents[1]
options=mp.tasks.vision.HandLandmarkerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path=str(ROOT/"assets/hand_landmarker.task"),delegate=mp.tasks.BaseOptions.Delegate.CPU),
    num_hands=2)
with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
    result=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.zeros((480,640,3),dtype=np.uint8)))
    assert len(result.hand_landmarks)==0
print(json.dumps({"mediapipe":mp.__version__,"native_inference":"passed","camera_opened":False}))
