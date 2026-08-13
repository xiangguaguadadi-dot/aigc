from __future__ import annotations

import torch


class PBRParameters(torch.nn.Module):
    def __init__(self, prior: dict[str, torch.Tensor], mode: str, epsilon: dict[str, float]) -> None:
        super().__init__()
        self.mode = mode
        for name, value in prior.items():
            self.register_buffer(f"prior_{name}", value.detach().clone())
        train_pbr = mode in {"unbounded_pbr_light", "bounded_pbr_light"}
        for name in ("base_color", "metallic", "roughness"):
            delta = torch.zeros_like(prior[name])
            setattr(self, f"delta_{name}", torch.nn.Parameter(delta, requires_grad=train_pbr))
        self.epsilon = epsilon

    def material(self) -> dict[str, torch.Tensor]:
        output = {"opacity": self.prior_opacity}
        for name, low in (("base_color", 0.0), ("metallic", 0.0), ("roughness", 0.04)):
            prior = getattr(self, f"prior_{name}")
            delta = getattr(self, f"delta_{name}")
            if self.mode == "unbounded_pbr_light":
                value = torch.sigmoid(torch.logit(prior.clamp(1e-4, 1 - 1e-4)) + delta)
            elif self.mode == "bounded_pbr_light":
                value = prior + self.epsilon[name] * torch.tanh(delta)
            else:
                value = prior
            output[name] = value.clamp(low, 1.0)
        return output

    def deltas(self) -> list[torch.Tensor]:
        return [self.delta_base_color, self.delta_metallic, self.delta_roughness]
