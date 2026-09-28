from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .errors import Idea54Error
from .geometry import unique_edges
from .lighting import LowDimensionalLight
from .losses import lighting_regularizers, masked_charbonnier, material_prior_loss, mesh_tv_loss
from .materials import PBRParameters
from .metrics import masked_mae, material_metrics, psnr
from .provenance import collect_provenance, write_provenance
from .renderer import NvdiffrastPBRRenderer, linear_to_srgb, srgb_to_linear
from .schema import AssetBundle

METHODS = ("prior", "lighting_only", "unbounded_pbr_light", "bounded_pbr_light")


def _torch_material(bundle: AssetBundle, device: str) -> dict[str, torch.Tensor]:
    return {name: torch.as_tensor(getattr(bundle.material, name), device=device) for name in ("base_color", "metallic", "roughness", "opacity")}


def _save_png(path: Path, value: torch.Tensor) -> None:
    image = linear_to_srgb(value.detach()).clamp(0, 1).mul(255).add(0.5).to(torch.uint8).cpu().numpy()
    Image.fromarray(image, mode="RGB").save(path)


def run_method(bundle: AssetBundle, method: str, config: dict, output: Path) -> dict:
    if method not in METHODS:
        raise Idea54Error("UNKNOWN_METHOD", method)
    if bundle.manifest.get("metadata", {}).get("observation_status") != "rendered":
        raise Idea54Error("OBSERVATION_NOT_RENDERED", "run make-synthetic on a CUDA machine")
    output.mkdir(parents=True, exist_ok=False)
    (output / "renders").mkdir()
    seed = int(config["seed"])
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    device = "cuda"
    renderer = NvdiffrastPBRRenderer()
    vertices = torch.as_tensor(bundle.geometry.vertices, device=device).detach()
    faces = torch.as_tensor(bundle.geometry.faces, device=device, dtype=torch.int32).detach()
    normals = torch.as_tensor(bundle.geometry.vertex_normals, device=device).detach()
    geometry_before = bundle.geometry.sha256
    (output / "geometry_before.sha256").write_text(geometry_before + "\n", encoding="ascii")
    prior = _torch_material(bundle, device)
    optimization = config["optimization"]
    epsilon = {
        "base_color": float(optimization["epsilon_base_color"]),
        "metallic": float(optimization["epsilon_metallic"]),
        "roughness": float(optimization["epsilon_roughness"]),
    }
    parameters = PBRParameters(prior, method, epsilon).to(device)
    train_light = method != "prior"
    lighting = LowDimensionalLight(trainable=train_light, device=device).to(device)
    trainable = [parameter for parameter in list(parameters.parameters()) + list(lighting.parameters()) if parameter.requires_grad]
    optimizer = torch.optim.Adam(trainable, lr=float(optimization["learning_rate"])) if trainable else None
    target_srgb = torch.as_tensor(bundle.observation, device=device)
    target = srgb_to_linear(target_srgb)
    mask = torch.as_tensor(bundle.mask, device=device)
    edges = unique_edges(faces.long())
    weights = optimization["weights"]
    rows = []
    steps = 0 if method == "prior" else int(optimization["steps"])
    for step in range(steps + 1):
        material = parameters.material()
        light_values = lighting.values()
        render = renderer.render(vertices, faces, normals, material, bundle.camera, light_values)
        rgb_loss = masked_charbonnier(render.rgb, target, mask)
        prior_loss = material_prior_loss(material, prior)
        tv_loss = mesh_tv_loss(parameters.deltas(), edges)
        energy_loss, white_balance_loss = lighting_regularizers(light_values)
        total = (
            float(weights["rgb"]) * rgb_loss
            + float(weights["prior"]) * prior_loss
            + float(weights["tv"]) * tv_loss
            + float(weights["light_energy"]) * energy_loss
            + float(weights["white_balance"]) * white_balance_loss
        )
        if not torch.isfinite(total):
            raise Idea54Error("NONFINITE_LOSS", f"step={step}")
        if optimizer is not None and step < steps:
            optimizer.zero_grad(set_to_none=True)
            total.backward()
            if vertices.grad is not None or normals.grad is not None:
                raise Idea54Error("INVALID_GEOMETRY_GRADIENT", f"step={step}")
            optimizer.step()
        if step % int(optimization["log_every"]) == 0 or step == steps:
            rows.append({"step": step, "loss": float(total.detach()), "rgb": float(rgb_loss.detach()), "prior": float(prior_loss.detach()), "tv": float(tv_loss.detach()), "light_energy": float(energy_loss.detach())})
    material = parameters.material()
    light_values = lighting.values()
    render = renderer.render(vertices, faces, normals, material, bundle.camera, light_values)
    _save_png(output / "renders" / "condition.png", render.rgb)
    arrays = {name: value.detach().cpu().numpy() for name, value in material.items()}
    np.savez(output / "corrected_material.npz", **arrays)
    np.savez(output / "learned_lighting.npz", **{name: value.detach().cpu().numpy() for name, value in light_values.items()})
    geometry_after = bundle.geometry.sha256
    (output / "geometry_after.sha256").write_text(geometry_after + "\n", encoding="ascii")
    if geometry_before != geometry_after:
        raise Idea54Error("INVALID_GEOMETRY_MUTATION", method)
    prediction = linear_to_srgb(render.rgb).detach().cpu().numpy()
    metrics = {"method": method, "condition_mae": masked_mae(prediction, bundle.observation, bundle.mask), "condition_psnr": psnr(prediction, bundle.observation, bundle.mask), "geometry_unchanged": True}
    gt_path = bundle.root / "evaluation" / "material_gt.npz"
    if gt_path.is_file():
        with np.load(gt_path, allow_pickle=False) as gt:
            metrics.update(material_metrics(arrays, {key: gt[key] for key in gt.files}))
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output / "optimization.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    write_provenance(output / "provenance.json", collect_provenance(bundle.root, seed))
    return metrics
