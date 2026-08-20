import torch
from torch import nn


class AIPDNet(nn.Module):
    """Small FPGA-friendly CNN for PD-array time-window prediction.

    Input:
        x: (batch, time_window, rows, cols)

    Outputs:
        power_log: (batch, rows, cols), future log10 normalized PD power
        phys: (batch, phys_dim), normalized physical parameters
    """

    def __init__(self, time_window, rows, cols, phys_dim=6, width=32):
        super().__init__()
        self.time_window = int(time_window)
        self.rows = int(rows)
        self.cols = int(cols)
        self.phys_dim = int(phys_dim)

        self.features = nn.Sequential(
            nn.Conv2d(self.time_window, width, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(width),
            nn.ReLU(inplace=True),
            nn.Conv2d(width, width, kernel_size=3, padding=1, groups=width, bias=False),
            nn.Conv2d(width, width * 2, kernel_size=1, bias=False),
            nn.BatchNorm2d(width * 2),
            nn.ReLU(inplace=True),
            nn.Conv2d(width * 2, width * 2, kernel_size=3, padding=1, groups=width * 2, bias=False),
            nn.Conv2d(width * 2, width * 2, kernel_size=1, bias=False),
            nn.BatchNorm2d(width * 2),
            nn.ReLU(inplace=True),
        )
        hidden = width * 2 * self.rows * self.cols
        self.power_head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(hidden, max(64, width * 2)),
            nn.ReLU(inplace=True),
            nn.Linear(max(64, width * 2), self.rows * self.cols),
        )
        self.phys_head = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(width * 2, max(32, width)),
            nn.ReLU(inplace=True),
            nn.Linear(max(32, width), self.phys_dim),
        )

    def forward(self, x):
        z = self.features(x)
        power_log = self.power_head(z).view(-1, self.rows, self.cols)
        phys = self.phys_head(z)
        return power_log, phys


def weights_from_power_log(power_log, temperature=1.0):
    """Differentiable normalized combiner weights from predicted log power."""
    b = power_log.shape[0]
    flat = power_log.reshape(b, -1) / max(float(temperature), 1e-6)
    return torch.softmax(flat, dim=1).reshape_as(power_log)
