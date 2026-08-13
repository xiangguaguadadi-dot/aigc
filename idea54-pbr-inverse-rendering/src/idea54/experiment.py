from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from .config import load_config
from .lighting import LowDimensionalLight
from .optimizer import run_method
from .renderer import NvdiffrastPBRRenderer, linear_to_srgb
from .schema import load_bundle
from .synthetic import make_synthetic_bundle, replace_observation


def render_synthetic_observation(root: Path) -> None:
    bundle = load_bundle(root)
    with np.load(root / "evaluation" / "material_gt.npz", allow_pickle=False) as gt:
        material = {key: torch.as_tensor(gt[key], device="cuda") for key in gt.files}
    renderer = NvdiffrastPBRRenderer()
    light = LowDimensionalLight(trainable=False, device="cuda")
    with torch.no_grad():
        light.log_intensity.copy_(torch.linspace(-1.0, -2.2, light.log_intensity.numel(), device="cuda").view_as(light.log_intensity))
        light.log_ambient.copy_(torch.tensor([-2.0, -2.2, -2.4], device="cuda"))
        render = renderer.render(
            torch.as_tensor(bundle.geometry.vertices, device="cuda"),
            torch.as_tensor(bundle.geometry.faces, device="cuda", dtype=torch.int32),
            torch.as_tensor(bundle.geometry.vertex_normals, device="cuda"),
            material,
            bundle.camera,
            light.values(),
        )
    rgb = linear_to_srgb(render.rgb).cpu().numpy()
    replace_observation(root, rgb, render.mask.cpu().numpy())


def make_synthetic_suite(config_path: str | Path, output: str | Path) -> list[Path]:
    config = load_config(config_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    roots = []
    for index, name in enumerate(config["objects"]):
        root = make_synthetic_bundle(output / f"object_{index:02d}_{name}", name, int(config["image_size"]), int(config["seed"]) + index)
        render_synthetic_observation(root)
        roots.append(root)
    return roots


def run_paired(bundle_path: str | Path, config_path: str | Path, output: str | Path) -> dict:
    config = load_config(config_path)
    bundle = load_bundle(bundle_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for method in config["methods"]:
        results[method] = run_method(bundle, method, config, output / method)
    (output / "paired_metrics.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def run_suite(bundle_root: str | Path, config_path: str | Path, output: str | Path) -> dict:
    bundle_root = Path(bundle_root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for bundle in sorted(path for path in bundle_root.iterdir() if (path / "manifest.json").is_file()):
        results[bundle.name] = run_paired(bundle, config_path, output / bundle.name)
    (output / "suite_metrics.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results
