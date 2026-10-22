#!/usr/bin/env python3
"""Rule-backend event metrics for filtered landmarks, computed in memory.

Same evaluation path as `airclay evaluate --backend rules` (Resampler -> Controller ->
label_at -> event_metrics, summed over recordings), but the frames are filtered on the
fly, so parameter sweeps do not write derived datasets to disk.

Examples (from the repository root):
    python scripts/filter_eval.py --split SPLIT --partition val --filter none
    python scripts/filter_eval.py --split SPLIT --partition val --filter kalman --r 9e-6 --q 1e-5 3e-5 1e-4
    python scripts/filter_eval.py --split SPLIT --partition test --filter ema --set combo_ms=0
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from airclay.config import config
from airclay.data_tools.dataset import label_at, read_recording, validate_split
from airclay.interaction.state import Controller
from airclay.learning.evaluate import event_metrics
from airclay.learning.features import LABELS, Resampler
import derive_filtered as filters

SUMMED = ("ground_truth_events", "predicted_events", "false_operations", "missed_operations",
          "wrong_mode_segments", "early_releases")


def run(recordings, cfg):
    """recordings: list of (meta, frames, annotations). Returns the aggregate event metrics."""
    results = []
    for meta, frames, ann in recordings:
        local = dict(cfg, dominant=meta.get("dominant", "Right"))
        controller, resampler = Controller(local), Resampler(local["fps"])
        times, truth, states = [], [], []
        for frame in frames:
            for sample in resampler.push(frame):
                state = controller.step(sample, None)
                times.append(sample["timestamp_ms"])
                truth.append(label_at(times[-1], ann))
                states.append(LABELS.index(state["mode"]))
        results.append(event_metrics(times, truth, states))
    minutes = sum(r["minutes"] for r in results)
    agg = {key: sum(r[key] for r in results) for key in SUMMED}
    agg["false_operations_per_minute"] = agg["false_operations"] / minutes
    for key in ("onset_delay_ms", "offset_delay_ms"):
        values = [x for r in results for x in r[key]]
        agg[key + "_median"] = float(np.median(values)) if values else None
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--partition", choices=["val", "test"], required=True)
    ap.add_argument("--filter", choices=["none", "ema", "kalman"], required=True)
    ap.add_argument("--alpha", type=float, default=0.45)
    ap.add_argument("--r", type=float, default=9e-6)
    ap.add_argument("--q", type=float, nargs="+", default=[None])
    ap.add_argument("--gap-ms", type=float, default=150.0)
    ap.add_argument("--set", action="append", default=[], help="config override, e.g. combo_ms=0")
    ap.add_argument("--output", help="write all rows as JSON here")
    a = ap.parse_args()
    cfg = config(None)
    for item in a.set:
        key, value = item.split("=", 1)
        cfg[key] = type(cfg[key])(float(value)) if isinstance(cfg[key], (int, float)) else value
    split = json.loads(Path(a.split).read_text())
    validate_split(split)
    raw = [read_recording(p, True) for p in split["recordings"][a.partition]]
    rows = []
    for q in a.q:
        if a.filter == "none":
            recs, params = raw, {}
        elif a.filter == "ema":
            recs, params = [(m, filters.ema_frames(f, a.alpha, a.gap_ms)[0], n) for m, f, n in raw], {"alpha": a.alpha}
        else:
            if q is None:
                sys.exit("--filter kalman needs --q")
            recs, params = [(m, filters.kalman_frames(f, q, a.r, a.gap_ms)[0], n) for m, f, n in raw], {"q": q, "r": a.r}
        row = {"filter": a.filter, **params, "partition": a.partition, "overrides": a.set, **run(recs, cfg)}
        rows.append(row)
        print(json.dumps(row))
    if a.output:
        Path(a.output).write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
