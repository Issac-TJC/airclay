import json
from pathlib import Path
import numpy as np
from airclay.learning.features import LABELS, preprocess


def read_recording(path, require_verified=False, allow_synthetic=False):
    path = Path(path)
    meta = json.loads((path / "metadata.json").read_text())
    annotations = json.loads((path / "annotations.json").read_text())
    if require_verified and not annotations.get("verified"):
        raise ValueError(f"{path}: annotations require human verification")
    if meta.get("synthetic") and require_verified and not allow_synthetic:
        raise ValueError("Synthetic fixtures only test plumbing; pass --allow-synthetic explicitly")
    frames = [json.loads(line) for line in (path / "frames.jsonl").read_text().splitlines() if line.strip()]
    if len(frames) < 2:
        raise ValueError(f"{path}: recording is too short")
    last_end = 0
    for segment in sorted(annotations["segments"], key=lambda s: s["start_ms"]):
        if segment["label"] not in LABELS or segment["start_ms"] < last_end or segment["end_ms"] <= segment["start_ms"]:
            raise ValueError(f"{path}: overlapping/invalid annotations")
        last_end = segment["end_ms"]
    return meta, frames, annotations


def label_at(t, annotations):
    for s in annotations["segments"]:
        if s["start_ms"] <= t < s["end_ms"]:
            return LABELS.index(s["label"])
    return 0


def create_split(data_root, output, seed=42, allow_small=False):
    paths = sorted(Path(data_root).glob("*/metadata.json"))
    subjects = sorted({json.loads(p.read_text())["subject"] for p in paths})
    if len(subjects) < (3 if allow_small else 5):
        raise ValueError("Need at least 5 subjects (3 with --allow-small for smoke tests)")
    rng = np.random.default_rng(seed)
    rng.shuffle(subjects)
    nval = max(1, int(len(subjects) * .2))
    ntest = max(1, int(len(subjects) * .2))
    groups = {"train": subjects[:len(subjects)-nval-ntest],
              "val": subjects[len(subjects)-nval-ntest:len(subjects)-ntest], "test": subjects[-ntest:]}
    result = {"seed": seed, "subjects": groups, "recordings": {}}
    for name, group in groups.items():
        result["recordings"][name] = [str(p.parent.resolve()) for p in paths if json.loads(p.read_text())["subject"] in group]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, indent=2))
    return result


def validate_split(split):
    seen = set()
    for name in ("train", "val", "test"):
        subjects = set(split["subjects"][name])
        if not subjects or seen & subjects:
            raise ValueError("Subject split is empty or leaks subjects")
        seen |= subjects
        for path in split["recordings"][name]:
            subject = json.loads((Path(path) / "metadata.json").read_text())["subject"]
            if subject not in subjects:
                raise ValueError("Recording assigned to the wrong subject split")


class Windows:
    def __init__(self, paths, cfg, stride=1, allow_synthetic=False):
        self.sequences, self.index, self.targets = [], [], []
        for path in paths:
            meta, frames, ann = read_recording(path, True, allow_synthetic)
            timed, x = preprocess(frames, cfg["fps"])
            seq = len(self.sequences)
            self.sequences.append(x)
            for end in range(cfg["window"] - 1, len(x), stride):
                self.index.append((seq, end))
                self.targets.append(label_at(timed[end]["timestamp_ms"], ann))
        self.window = cfg["window"]
        if not self.index:
            raise ValueError("No windows; collect longer recordings")

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        import torch
        seq, end = self.index[index]
        return torch.from_numpy(self.sequences[seq][end-self.window+1:end+1]), self.targets[index]
