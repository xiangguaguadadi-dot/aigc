from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from ..errors import Idea54Error
from ..geometry import vertex_normals
from ..hashing import sha256_file

REQUIRED_KEYS = {"vertices", "faces", "base_color", "metallic", "roughness", "opacity"}


def adapt_explicit_dump(dump: str | Path, camera: str | Path, observation: str | Path, mask: str | Path, output: str | Path, upstream_commit: str) -> Path:
    dump = Path(dump)
    output = Path(output)
    if output.exists():
        raise Idea54Error("OUTPUT_EXISTS", str(output))
    with np.load(dump, allow_pickle=False) as arrays:
        if not REQUIRED_KEYS.issubset(arrays.files):
            raise Idea54Error("UNSUPPORTED_TRELLIS_LAYOUT", f"required keys: {sorted(REQUIRED_KEYS)}")
        values = {key: arrays[key] for key in REQUIRED_KEYS}
        normals = arrays["vertex_normals"] if "vertex_normals" in arrays.files else vertex_normals(values["vertices"], values["faces"])
    output.mkdir(parents=True)
    np.savez(output / "geometry.npz", vertices=values["vertices"], faces=values["faces"], vertex_normals=normals)
    np.savez(output / "material_prior.npz", **{key: values[key] for key in ("base_color", "metallic", "roughness", "opacity")})
    shutil.copyfile(camera, output / "camera.json")
    shutil.copyfile(observation, output / "observation.png")
    shutil.copyfile(mask, output / "observation_mask.png")
    paths = {"geometry": "geometry.npz", "material_prior": "material_prior.npz", "camera": "camera.json", "observation": "observation.png", "mask": "observation_mask.png"}
    manifest = {
        "schema_version": "pbr-asset-bundle-v1",
        "source": "user-provided-trellis2-explicit-dump",
        "coordinate_system": "declared-by-user",
        "units": "unitless",
        "metadata": {"upstream_commit": upstream_commit, "observation_status": "user-provided"},
        "files": {key: {"path": value, "sha256": sha256_file(output / value)} for key, value in paths.items()},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
