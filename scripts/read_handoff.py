import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(root, videos=False):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    files = dict(manifest["files"])
    if videos:
        files.update(manifest["video_files"])
    for name, expected in files.items():
        path = root / name
        if not path.is_file() or sha256(path) != expected["sha256"]:
            raise ValueError(f"Missing or changed file: {name}")
    return len(files)


def load_session(root, session):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    if session not in {row["session_id"] for row in manifest["sessions"]}:
        raise ValueError(f"Unknown session: {session}")
    folder = root / "data" / session
    with np.load(folder / "landmarks.npz", allow_pickle=False) as saved:
        arrays = {key: saved[key] for key in saved.files}
    metadata = json.loads((folder / "metadata.json").read_text())
    return arrays, metadata


def iter_takes(arrays):
    for index, take_id in enumerate(arrays["take_ids"]):
        mask = arrays["take_index"] == index
        yield str(take_id), {key: value[mask] for key, value in arrays.items()
                             if key != "take_ids"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--videos", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((args.package / "manifest.json").read_text())
    if args.verify:
        print(f"Verified files: {verify_package(args.package, args.videos)}")
    session = args.session or manifest["sessions"][0]["session_id"]
    arrays, metadata = load_session(args.package, session)
    print(json.dumps({"dataset": manifest["dataset_id"], "session": session,
                      "frames": len(arrays["label"]), "image_shape": list(arrays["image"].shape),
                      "takes": len(arrays["take_ids"]), "dominant": metadata["dominant"]}, indent=2))


if __name__ == "__main__":
    main()
