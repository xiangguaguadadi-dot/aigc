from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .metrics import paired_bootstrap_ci


def generate_report(runs: str | Path, output: str | Path) -> Path:
    runs = Path(runs)
    suite_path = runs / "suite_metrics.json"
    if suite_path.is_file():
        payload = json.loads(suite_path.read_text(encoding="utf-8"))
    else:
        payload = {}
        for path in sorted(runs.rglob("paired_metrics.json")):
            payload[path.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    methods = sorted({method for result in payload.values() for method in result})
    lines = ["# Idea 5.4 experiment report", "", "This report distinguishes condition-view fit from synthetic PBR-ground-truth evidence.", "", "## Per-object results", ""]
    lines.append("| Object | Method | Condition MAE | Condition PSNR | Base-color MAE | Metallic MAE | Roughness MAE | Geometry frozen |")
    lines.append("|---|---|---:|---:|---:|---:|---:|:---:|")
    for object_name, result in payload.items():
        for method, metrics in result.items():
            lines.append(
                f"| {object_name} | {method} | {metrics['condition_mae']:.6f} | {metrics['condition_psnr']:.3f} | "
                f"{metrics.get('base_color_mae', float('nan')):.6f} | {metrics.get('metallic_mae', float('nan')):.6f} | "
                f"{metrics.get('roughness_mae', float('nan')):.6f} | {'yes' if metrics['geometry_unchanged'] else 'no'} |"
            )
    if payload and "bounded_pbr_light" in methods and "prior" in methods:
        deltas = []
        for result in payload.values():
            bounded = np.mean([result["bounded_pbr_light"][key] for key in ("base_color_mae", "metallic_mae", "roughness_mae")])
            prior = np.mean([result["prior"][key] for key in ("base_color_mae", "metallic_mae", "roughness_mae")])
            deltas.append(prior - bounded)
        low, high = paired_bootstrap_ci(np.asarray(deltas))
        lines.extend(["", "## Paired material evidence", "", f"Median reduction in aggregate PBR MAE: `{np.median(deltas):.6f}`.", f"Bootstrap 95% CI for the mean paired reduction: `[{low:.6f}, {high:.6f}]`."])
    lines.extend(["", "## Evidence boundary", "", "Synthetic PBR ground truth can validate the optimizer under controlled rendering. Real single-image runs without material ground truth establish fit and geometry preservation only; they do not establish real-material accuracy.", ""])
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
