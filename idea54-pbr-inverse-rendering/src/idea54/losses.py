from __future__ import annotations

import torch


def masked_charbonnier(prediction: torch.Tensor, target: torch.Tensor, mask: torch.Tensor, epsilon: float = 1e-3) -> torch.Tensor:
    if mask.ndim == 2:
        mask = mask[..., None]
    denominator = mask.sum() * prediction.shape[-1]
    if float(denominator.detach().cpu()) <= 0:
        raise ValueError("mask is empty")
    return (torch.sqrt((prediction - target).square() + epsilon**2) * mask).sum() / denominator


def material_prior_loss(material: dict[str, torch.Tensor], prior: dict[str, torch.Tensor]) -> torch.Tensor:
    return sum((material[name] - prior[name]).square().mean() for name in ("base_color", "metallic", "roughness"))


def mesh_tv_loss(deltas: list[torch.Tensor], edges: torch.Tensor) -> torch.Tensor:
    if edges.numel() == 0:
        return deltas[0].new_zeros(())
    return sum((delta[edges[:, 0]] - delta[edges[:, 1]]).abs().mean() for delta in deltas)


def lighting_regularizers(light: dict[str, torch.Tensor]) -> tuple[torch.Tensor, torch.Tensor]:
    energy = light["intensity"].mean() + light["ambient"].mean()
    energy_loss = (energy - 0.35).square() + light["intensity"].var()
    white_balance_loss = (light["white_balance"] - 1.0).square().mean()
    return energy_loss, white_balance_loss
