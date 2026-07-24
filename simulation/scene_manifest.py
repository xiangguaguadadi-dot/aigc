"""Validated interactive-scene manifests shared by preprocessing and simulation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MANIFEST_VERSION = 1


def load_scene_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("format_version") != MANIFEST_VERSION:
        raise ValueError(f"Unsupported scene manifest: {manifest_path}")
    objects = data.get("objects")
    if not isinstance(objects, list) or not objects:
        raise ValueError("Scene manifest requires at least one object")

    ids = set()
    for item in objects:
        if not isinstance(item, dict):
            raise ValueError("Every scene object must be a JSON object")
        object_id = str(item.get("id", "")).strip()
        if not object_id or object_id in ids:
            raise ValueError(f"Invalid or duplicate scene object id: {object_id!r}")
        ids.add(object_id)
        source = Path(str(item.get("source_path", "")))
        if not source.is_absolute():
            source = (manifest_path.parent / source).resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        item["source_path"] = str(source)
        item["position"] = _vector(item.get("position", [0.0, 0.0, 0.0]), 3, "position")
        item["orientation"] = _vector(
            item.get("orientation", [0.0, 0.0, 0.0, 1.0]), 4, "orientation"
        )
        item["scale"] = _positive(item.get("scale", 1.0), "scale")
        item["dynamic"] = bool(item.get("dynamic", False))
        item["mass_kg"] = _positive(item.get("mass_kg", 0.5), "mass_kg")
        item["friction"] = max(0.0, float(item.get("friction", 0.5)))

    active_id = str(data.get("active_object_id", "")).strip()
    if active_id not in ids:
        active_id = next(
            (item["id"] for item in objects if item.get("dynamic")),
            objects[0]["id"],
        )
    data["active_object_id"] = active_id
    data["manifest_path"] = str(manifest_path)
    return data


def write_scene_manifest(path: str | Path, data: dict[str, Any]) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    temporary.replace(output)
    return output


def _vector(value: Any, length: int, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"{field} must contain {length} numbers")
    return [float(component) for component in value]


def _positive(value: Any, field: str) -> float:
    result = float(value)
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result
