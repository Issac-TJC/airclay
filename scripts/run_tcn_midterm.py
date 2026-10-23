"""Run the frozen three-seed human-data TCN experiment and aggregate results.

This script deliberately rejects synthetic or unverified recordings. Use the
ordinary CLI with --allow-synthetic for plumbing-only smoke tests.
"""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np

from airclay.config import ROOT
from airclay.data_tools.dataset import Windows, read_recording, validate_split


SEEDS = (42, 43, 44)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_state():
    def run(*args):
        return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    try:
        return {"revision": run("git", "rev-parse", "HEAD"),
                "dirty": bool(run("git", "status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "dirty": None}


def validate_preprocessing_manifest(preprocessing_path, recordings):
    """Accept the legacy flat manifest or derive_filtered.py's release manifest."""
    preprocessing = json.loads(preprocessing_path.read_text())
    filter_spec = preprocessing.get("filter")
    if isinstance(filter_spec, dict):
        filter_name = filter_spec.get("name")
        alpha = filter_spec.get("alpha", -1)
    else:
        filter_name = filter_spec
        alpha = preprocessing.get("alpha", -1)
    if filter_name != "ema" or float(alpha) != 0.45:
        raise ValueError("Preprocessing manifest must declare EMA with alpha=0.45")

    if "sessions" in preprocessing:
        # Native output of scripts/derive_filtered.py. Its manifest sits beside data/.
        expected_root = (preprocessing_path.parent / "data").resolve()
        requested = {Path(path).resolve().name for path in recordings}
        covered = set(preprocessing["sessions"])
        if covered != requested:
            raise ValueError("Derived manifest sessions must exactly match the fixed split")
        outside = [path for path in recordings if Path(path).resolve().parent != expected_root]
        if outside:
            raise ValueError(
                "Split recordings must come from the derived release beside derived_manifest.json"
            )
    else:
        # Backward-compatible hand-written manifest used by the original TCN branch.
        covered = {str(Path(path).resolve()) for path in preprocessing.get("recordings", [])}
        if covered != recordings:
            raise ValueError("Preprocessing manifest recordings must exactly match the fixed split")
    return preprocessing


def preflight(split_path, preprocessing_path):
    split = json.loads(split_path.read_text())
    validate_split(split)
    empty = [name for name in ("train", "val", "test") if not split["recordings"][name]]
    if empty:
        raise ValueError(f"Recording partitions must be non-empty: {empty}")
    recordings = {str(Path(path).resolve()) for name in ("train", "val", "test")
                  for path in split["recordings"][name]}
    for path in sorted(recordings):
        metadata = json.loads((Path(path) / "metadata.json").read_text())
        if metadata.get("synthetic") is not False:
            raise ValueError(f"{path}: formal experiment requires metadata synthetic=false")
        read_recording(path, require_verified=True, allow_synthetic=False)

    preprocessing = validate_preprocessing_manifest(preprocessing_path, recordings)

    cfg = json.loads((ROOT / "configs/train.json").read_text())
    training = Windows(split["recordings"]["train"], cfg)
    counts = np.bincount(training.targets, minlength=4)
    if np.any(counts == 0):
        raise ValueError(f"All four labels must appear in training; counts={counts.tolist()}")
    return split, preprocessing, counts.tolist()


def invoke(*args):
    command = [sys.executable, "-m", "airclay.cli", *map(str, args)]
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def metric_values(report):
    classification, events = report["classification"], report["events"]
    profile = report["model_profile"]
    return {"macro_f1": classification["macro avg"]["f1-score"],
            "recall": {label: classification[label]["recall"]
                       for label in ("idle", "sculpt", "orbit", "resize")},
            "false_operations_per_minute": events["false_operations_per_minute"],
            "missed_operations": events["missed_operations"],
            "early_releases": events["early_releases"],
            "onset_delay_ms_median": events["onset_delay_ms_median"],
            "offset_delay_ms_median": events["offset_delay_ms_median"],
            "parameters": profile["parameters"], "model_median_ms": profile["median_ms"],
            "model_p95_ms": profile["p95_ms"]}


def aggregate(values):
    def stats(items):
        numeric = [float(value) for value in items if value is not None]
        return {"mean": float(np.mean(numeric)) if numeric else None,
                "std": float(np.std(numeric, ddof=1)) if len(numeric) > 1 else 0.0 if numeric else None}
    result = {}
    for key in ("macro_f1", "false_operations_per_minute", "missed_operations", "early_releases",
                "onset_delay_ms_median", "offset_delay_ms_median", "model_median_ms", "model_p95_ms"):
        result[key] = stats([item[key] for item in values])
    result["recall"] = {label: stats([item["recall"][label] for item in values])
                        for label in ("idle", "sculpt", "orbit", "resize")}
    result["parameters"] = values[0]["parameters"]
    return result


def main():
    parser = argparse.ArgumentParser(description="Frozen three-seed AirClay TCN midterm experiment")
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--preprocessing-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/midterm/tcn")
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    args = parser.parse_args()
    args.split, args.preprocessing_manifest = args.split.resolve(), args.preprocessing_manifest.resolve()
    if not args.split.is_file() or not args.preprocessing_manifest.is_file():
        parser.error("split and preprocessing manifest must exist")
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        parser.error("output must be absent or empty; preserve formal experiment evidence")

    try:
        split, preprocessing, counts = preflight(args.split, args.preprocessing_manifest)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"experiment": "causal_tcn_midterm", "seeds": list(SEEDS),
                "split": str(args.split), "split_sha256": digest(args.split),
                "preprocessing_manifest": str(args.preprocessing_manifest),
                "preprocessing_sha256": digest(args.preprocessing_manifest),
                "preprocessing": preprocessing, "training_window_counts": counts,
                "source": git_state(), "python": platform.python_version(),
                "platform": platform.platform(),
                "config": {**json.loads((ROOT / "configs/train.json").read_text()),
                           "device": args.device}}
    (args.output / "experiment_manifest.json").write_text(json.dumps(manifest, indent=2))

    # Freeze the implementation/configuration before any test-partition evaluation.
    for seed in SEEDS:
        run = args.output / f"seed{seed}"
        invoke("train", "--model", "tcn", "--split", args.split, "--output", run,
               "--epochs", "50", "--seed", str(seed), "--device", args.device)
    for seed in SEEDS:
        run = args.output / f"seed{seed}"
        invoke("evaluate", "--backend", "tcn", "--checkpoint", run / "best.pt",
               "--split", args.split, "--partition", "val", "--output", run / "evaluation_val")
    for seed in SEEDS:
        run = args.output / f"seed{seed}"
        invoke("evaluate", "--backend", "tcn", "--checkpoint", run / "best.pt",
               "--split", args.split, "--partition", "test", "--output", run / "evaluation_test")

    per_seed, failure_cases = {}, []
    for seed in SEEDS:
        path = args.output / f"seed{seed}/evaluation_test/metrics.json"
        report = json.loads(path.read_text())
        per_seed[str(seed)] = metric_values(report)
        for recording in report["recordings"]:
            for failure in recording["failure_intervals"]:
                failure_cases.append({"seed": seed, "recording": recording["recording"], **failure,
                                      "duration_ms": failure["end_ms"] - failure["start_ms"]})
    values = list(per_seed.values())
    summary = {"synthetic": False, "per_seed": per_seed, "aggregate": aggregate(values),
               "main_confusion_matrix": str(args.output / "seed42/evaluation_test/confusion.png")}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    failure_cases.sort(key=lambda item: item["duration_ms"], reverse=True)
    (args.output / "failure_cases.json").write_text(json.dumps(failure_cases[:2], indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
