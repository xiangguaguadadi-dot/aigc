from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

import torch


def collect_provenance(root: Path, seed: int) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = "unavailable"
    try:
        import nvdiffrast

        nvdiffrast_version = getattr(nvdiffrast, "__version__", "unknown")
    except Exception:
        nvdiffrast_version = "unavailable"
    return {
        "git_commit": commit,
        "seed": seed,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "nvdiffrast": nvdiffrast_version,
    }


def write_provenance(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
