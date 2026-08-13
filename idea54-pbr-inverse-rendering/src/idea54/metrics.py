from __future__ import annotations

import math

import numpy as np


def masked_mae(prediction: np.ndarray, target: np.ndarray, mask: np.ndarray) -> float:
    selected = mask > 0.5
    if not selected.any():
        raise ValueError("mask is empty")
    return float(np.abs(prediction[selected] - target[selected]).mean())


def psnr(prediction: np.ndarray, target: np.ndarray, mask: np.ndarray | None = None) -> float:
    error = (prediction - target) ** 2
    if mask is not None:
        selected = mask > 0.5
        error = error[selected]
    mse = float(np.mean(error))
    return float("inf") if mse == 0 else -10.0 * math.log10(mse)


def material_metrics(material: dict[str, np.ndarray], truth: dict[str, np.ndarray]) -> dict[str, float]:
    return {
        "base_color_mae": float(np.abs(material["base_color"] - truth["base_color"]).mean()),
        "metallic_mae": float(np.abs(material["metallic"] - truth["metallic"]).mean()),
        "roughness_mae": float(np.abs(material["roughness"] - truth["roughness"]).mean()),
    }


def paired_bootstrap_ci(values: np.ndarray, seed: int = 42, samples: int = 10000) -> tuple[float, float]:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("values must be a non-empty vector")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, values.size, size=(samples, values.size))
    means = values[indices].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))
