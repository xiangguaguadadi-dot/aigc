from __future__ import annotations

import math

import torch


def fibonacci_directions(count: int, device: torch.device | str = "cpu") -> torch.Tensor:
    index = torch.arange(count, dtype=torch.float32, device=device)
    golden = math.pi * (3.0 - math.sqrt(5.0))
    y = 1.0 - 2.0 * (index + 0.5) / count
    radius = torch.sqrt((1.0 - y * y).clamp_min(0.0))
    theta = golden * index
    return torch.stack([radius * torch.cos(theta), y, radius * torch.sin(theta)], dim=1)


class LowDimensionalLight(torch.nn.Module):
    def __init__(self, count: int = 12, trainable: bool = True, device: str = "cpu") -> None:
        super().__init__()
        self.register_buffer("directions", fibonacci_directions(count, device))
        self.log_intensity = torch.nn.Parameter(torch.full((count, 3), -1.5, device=device), requires_grad=trainable)
        self.log_ambient = torch.nn.Parameter(torch.full((3,), -2.0, device=device), requires_grad=trainable)
        self.log_exposure = torch.nn.Parameter(torch.zeros((), device=device), requires_grad=trainable)
        self.white_balance_raw = torch.nn.Parameter(torch.zeros(3, device=device), requires_grad=trainable)

    def values(self) -> dict[str, torch.Tensor]:
        intensity = torch.nn.functional.softplus(self.log_intensity)
        ambient = torch.nn.functional.softplus(self.log_ambient)
        exposure = torch.exp(self.log_exposure.clamp(-3.0, 3.0))
        white_balance = torch.exp(self.white_balance_raw - self.white_balance_raw.mean())
        return {"directions": self.directions, "intensity": intensity, "ambient": ambient, "exposure": exposure, "white_balance": white_balance}
