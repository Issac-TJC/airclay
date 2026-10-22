import torch
from torch import nn
from torch.nn import functional as F
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


class CausalConv1d(nn.Conv1d):
    """A length-preserving convolution that can only read current/past samples."""

    def __init__(self, in_channels, out_channels, kernel_size, dilation=1):
        super().__init__(in_channels, out_channels, kernel_size, dilation=dilation, padding=0)
        self.left_padding = (kernel_size - 1) * dilation

    def forward(self, x):
        return super().forward(F.pad(x, (self.left_padding, 0)))


class TCNBlock(nn.Module):
    def __init__(self, channels, kernel_size, dilation, dropout):
        super().__init__()
        self.conv1 = CausalConv1d(channels, channels, kernel_size, dilation)
        self.conv2 = CausalConv1d(channels, channels, kernel_size, dilation)
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        residual = x
        x = self.dropout(self.activation(self.conv1(x)))
        x = self.dropout(self.activation(self.conv2(x)))
        return self.activation(x + residual)


class TCN(nn.Module):
    """Lightweight causal temporal convolutional intent classifier."""

    def __init__(self, channels=64, kernel_size=3, dilations=(1, 2, 4), dropout=.2, **_):
        super().__init__()
        if channels <= 0 or kernel_size <= 0 or not dilations or any(d <= 0 for d in dilations):
            raise ValueError("TCN channels, kernel size, and dilations must be positive")
        self.projection = nn.Conv1d(FEATURE_DIM, channels, 1)
        self.blocks = nn.ModuleList(
            TCNBlock(channels, kernel_size, dilation, dropout) for dilation in dilations
        )
        self.head = nn.Conv1d(channels, 4, 1)

    def forward_sequence(self, x):
        """Return logits for every causal prefix as [batch, time, class]."""
        x = self.projection(x.transpose(1, 2))
        for block in self.blocks:
            x = block(x)
        return self.head(x).transpose(1, 2)

    def forward(self, x):
        return self.forward_sequence(x)[:, -1]


def make_model(kind, cfg):
    if kind == "gru":
        return GRU(**{k: cfg[k] for k in ("hidden", "layers", "dropout")})
    if kind == "mlp":
        return MLP(**{k: cfg[k] for k in ("hidden", "layers", "dropout")})
    if kind == "tcn":
        return TCN(channels=cfg["tcn_channels"], kernel_size=cfg["tcn_kernel_size"],
                   dilations=tuple(cfg["tcn_dilations"]), dropout=cfg["dropout"])
    raise ValueError("Model must be mlp, gru, or tcn")
