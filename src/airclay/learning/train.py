import json
import random
from pathlib import Path
import numpy as np
import torch
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader
from airclay.config import ROOT
from airclay.data_tools.dataset import Windows, validate_split
from .features import LABELS, FEATURE_VERSION, FEATURE_DIM
from .models import make_model


def train(args):
    cfg = json.loads((ROOT / "configs/train.json").read_text())
    for key in ("epochs", "seed", "device"):
        if getattr(args, key, None) is not None:
            cfg[key] = getattr(args, key)
    random.seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])
    torch.set_num_threads(2)
    if cfg["device"] == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS is not available; use --device cpu")
    split = json.loads(Path(args.split).read_text())
    validate_split(split)
    train_data = Windows(split["recordings"]["train"], cfg, stride=3, allow_synthetic=args.allow_synthetic)
    val_data = Windows(split["recordings"]["val"], cfg, allow_synthetic=args.allow_synthetic)
    generator = torch.Generator().manual_seed(cfg["seed"])
    loader = DataLoader(train_data, batch_size=cfg["batch_size"], shuffle=True, generator=generator)
    val_loader = DataLoader(val_data, batch_size=cfg["batch_size"])
    model = make_model(args.model, cfg).to(cfg["device"])
    counts = np.bincount(train_data.targets, minlength=4)
    if np.any(counts == 0):
        raise ValueError(f"All four labels must appear in training; counts={counts.tolist()}")
    weights = counts.sum() / (4 * counts)
    loss_fn = torch.nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32, device=cfg["device"]))
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["lr"])
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "split.json").write_text(json.dumps(split, indent=2))
    log, best, stale = [], -1, 0
    for epoch in range(cfg["epochs"]):
        model.train()
        losses = []
        for x, y in loader:
            x, y = x.to(cfg["device"]), y.to(cfg["device"])
            optimizer.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
            losses.append(loss.item())
        model.eval()
        truth, predictions = [], []
        with torch.inference_mode():
            for x, y in val_loader:
                predictions.extend(model(x.to(cfg["device"])).argmax(-1).cpu().tolist())
                truth.extend(y.tolist())
        score = f1_score(truth, predictions, labels=list(range(4)), average="macro", zero_division=0)
        entry = {"epoch": epoch + 1, "loss": float(np.mean(losses)), "val_macro_f1": score}
        log.append(entry)
        print(json.dumps(entry), flush=True)
        if score > best:
            best, stale = score, 0
            torch.save({"kind": args.model, "config": cfg, "feature_version": FEATURE_VERSION,
                        "feature_dim": FEATURE_DIM, "labels": LABELS,
                        "state_dict": {k: v.cpu() for k, v in model.state_dict().items()},
                        "synthetic_smoke_only": args.allow_synthetic, "val_macro_f1": score}, out / "best.pt")
        else:
            stale += 1
        (out / "training.json").write_text(json.dumps(log, indent=2))
        if stale >= cfg["patience"]:
            break
    print(f"Saved {out / 'best.pt'}")
