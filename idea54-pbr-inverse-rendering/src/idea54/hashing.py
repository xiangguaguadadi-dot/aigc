from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def geometry_sha256(vertices: np.ndarray, faces: np.ndarray, normals: np.ndarray) -> str:
    digest = hashlib.sha256()
    for name, array, dtype in (
        ("vertices", vertices, "<f4"),
        ("faces", faces, "<i4"),
        ("vertex_normals", normals, "<f4"),
    ):
        canonical = np.ascontiguousarray(array, dtype=np.dtype(dtype))
        digest.update(name.encode("ascii"))
        digest.update(str(canonical.shape).encode("ascii"))
        digest.update(canonical.tobytes())
    return digest.hexdigest()
