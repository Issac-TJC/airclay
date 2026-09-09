import torch
from torch import nn
from .features import FEATURE_DIM, STATIC_INDICES


class GRU(nn.Module):
    def __init__(self, hidden=128, layers=2, dropout=.2):
        super().__init__()
        self.gru = nn.GRU(FEATURE_DIM, hidden, layers, batch_first=True,
                          dropout=dropout if layers > 1 else 0., bidirectional=False)
        self.head = nn.Linear(hidden, 4)

    def forward(self, x):
        output, _ = self.gru(x)
        return self.head(output[:, -1])


class MLP(nn.Module):
    def __init__(self, hidden=128, dropout=.2, **_):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(len(STATIC_INDICES), hidden), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden, 4))

    def forward(self, x):
        return self.net(x[:, -1, STATIC_INDICES])


def make_model(kind, cfg):
    if kind not in ("mlp", "gru"):
        raise ValueError("Model must be mlp or gru")
    return (GRU if kind == "gru" else MLP)(**{k: cfg[k] for k in ("hidden", "layers", "dropout")})
