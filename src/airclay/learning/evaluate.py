import json
from pathlib import Path
import numpy as np
from sklearn.metrics import classification_report, confusion_matrix
from airclay.config import config
from airclay.data_tools.dataset import read_recording, label_at, validate_split
from airclay.interaction.state import Controller
from .features import LABELS, Resampler


def segments(times, labels):
    result = []
    if not labels:
        return result
    start, current = times[0], labels[0]
    step = np.median(np.diff(times)) if len(times) > 1 else 33.333
    for t, label in zip(times[1:] + [times[-1] + step], labels[1:] + [-1]):
        if label != current:
            if current > 0:
                result.append({"start": start, "end": t, "label": current})
            start, current = t, label
    return result


def event_metrics(times, truth, predicted):
    gt, pred = segments(times, truth), segments(times, predicted)
    matches, used = [], set()
    for g in gt:
        candidates = [(max(0, min(g["end"], p["end"]) - max(g["start"], p["start"])), j)
                      for j, p in enumerate(pred) if j not in used and p["label"] == g["label"]]
        overlap, j = max(candidates, default=(0, -1))
        if overlap > 0:
            used.add(j)
            matches.append((g, pred[j]))
    duration = max((times[-1] - times[0]) / 60000, 1e-6) if len(times) > 1 else 1e-6
    wrong_mode = sum(any(max(g["start"], p["start"]) < min(g["end"], p["end"]) and g["label"] != p["label"] for g in gt) for p in pred)
    return {"minutes": duration, "ground_truth_events": len(gt), "predicted_events": len(pred),
            "false_operations": len(pred) - len(used), "false_operations_per_minute": (len(pred)-len(used))/duration,
            "missed_operations": len(gt)-len(matches), "wrong_mode_segments": wrong_mode,
            "early_releases": int(sum(p["end"] < g["end"]-100 for g, p in matches)),
            "onset_delay_ms": [p["start"]-g["start"] for g,p in matches],
            "offset_delay_ms": [p["end"]-g["end"] for g,p in matches]}


def evaluate(args):
    cfg = config(args.config)
    split = json.loads(Path(args.split).read_text())
    validate_split(split)
    truth_all, pred_all, state_all, results = [], [], [], []
    for path in split["recordings"][args.partition]:
        meta, frames, ann = read_recording(path, True, args.allow_synthetic)
        cfg["dominant"] = meta.get("dominant", "Right")
        controller = Controller(cfg)
        predictor = None
        if args.backend != "rules":
            from .inference import Predictor
            predictor = Predictor(args.checkpoint, args.backend)
        resampler = Resampler(predictor.cfg["fps"] if predictor else cfg["fps"])
        times, truth, predictions, states = [], [], [], []
        for frame in frames:
            for sample in resampler.push(frame):
                intent = predictor.step(sample) if predictor else None
                state = controller.step(sample, intent)
                times.append(sample["timestamp_ms"])
                truth.append(label_at(times[-1], ann))
                predictions.append(LABELS.index(intent if predictor else state["rule_intent"]))
                states.append(LABELS.index(state["mode"]))
        results.append({"recording": path, **event_metrics(times, truth, states)})
        truth_all.extend(truth)
        pred_all.extend(predictions)
        state_all.extend(states)
    if not truth_all:
        raise ValueError("No recordings in partition")
    matrix = confusion_matrix(truth_all, pred_all, labels=list(range(4)))
    minutes = sum(r["minutes"] for r in results)
    aggregate = {key: sum(r[key] for r in results) for key in ("ground_truth_events", "predicted_events", "false_operations", "missed_operations", "wrong_mode_segments", "early_releases")}
    aggregate["false_operations_per_minute"] = aggregate["false_operations"] / minutes
    for key in ("onset_delay_ms", "offset_delay_ms"):
        values = [x for r in results for x in r[key]]
        aggregate[key + "_median"] = float(np.median(values)) if values else None
    report = {"backend": args.backend, "partition": args.partition, "synthetic_smoke_only": args.allow_synthetic,
              "classification": classification_report(truth_all, pred_all, labels=list(range(4)), target_names=LABELS, output_dict=True, zero_division=0),
              "state_classification": classification_report(truth_all, state_all, labels=list(range(4)), target_names=LABELS, output_dict=True, zero_division=0),
              "confusion_matrix": matrix.tolist(), "events": aggregate, "recordings": results}
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(report, indent=2))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.imshow(matrix, cmap="Blues")
    ax.set(xticks=range(4), yticks=range(4), xticklabels=LABELS, yticklabels=LABELS,
           xlabel="Predicted", ylabel="True", title=f"{args.backend} / {args.partition}" + (" (synthetic smoke only)" if args.allow_synthetic else ""))
    for i in range(4):
        for j in range(4):
            ax.text(j, i, str(matrix[i,j]), ha="center", va="center")
    fig.tight_layout()
    fig.savefig(out / "confusion.png", dpi=160)
    plt.close(fig)
    print(json.dumps({"macro_f1": report["classification"]["macro avg"]["f1-score"], "events": aggregate}, indent=2))
