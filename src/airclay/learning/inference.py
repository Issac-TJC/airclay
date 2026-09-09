from collections import deque
from pathlib import Path
import numpy as np
import torch
from .features import Features, Resampler, FEATURE_VERSION, FEATURE_DIM, LABELS
from .models import make_model


class Predictor:
    def __init__(self, checkpoint, expected=None):
        if not checkpoint or not Path(checkpoint).is_file():
            raise ValueError("A valid --checkpoint is required; use --backend rules before training")
        ck = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if ck.get("feature_version") != FEATURE_VERSION or ck.get("labels") != LABELS or ck.get("feature_dim") != FEATURE_DIM:
            raise ValueError("Checkpoint feature/label schema mismatch")
        if expected and ck["kind"] != expected:
            raise ValueError("Checkpoint model does not match selected backend")
        self.cfg = ck["config"]
        self.model = make_model(ck["kind"], self.cfg)
        self.model.load_state_dict(ck["state_dict"])
        self.model.eval()
        torch.set_num_threads(1)
        self.features = Features()
        self.buffer = deque(maxlen=self.cfg["window"])

    def step(self, frame):
        self.buffer.append(self.features.step(frame))
        if len(self.buffer) < self.buffer.maxlen:
            return "idle"
        with torch.inference_mode():
            x = torch.from_numpy(np.stack(self.buffer)).unsqueeze(0)
            return LABELS[self.model(x).argmax(-1).item()]
