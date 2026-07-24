"""Split a reconstructed GLB into physical entities and write a scene manifest."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

from simulation.scene_manifest import MANIFEST_VERSION, write_scene_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an automatic multi-object interaction scene")
    parser.add_argument("--input", required=True, help="Source GLB, GLTF, OBJ, or PLY")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--source-image", default=None, help="Optional source image provenance")
    parser.add_argument("--scale", type=float, default=1.0, help="Metric calibration scale")
    parser.add_argument(
        "--target-max-dimension",
        type=float,
        default=None,
        help="Calibrate the complete source so its largest dimension has this many meters",
    )
    parser.add_argument("--origin", default="0.75,0.15,0", help="Scene origin x,y,z in meters")
    parser.add_argument("--labels", default=None, help="Optional comma-separated labels after sorting")
    parser.add_argument("--active", default=None, help="Optional active object id or label")
    parser.add_argument("--active-mass", type=float, default=None)
    parser.add_argument("--active-friction", type=float, default=None)
    parser.add_argument("--voxel-resolution", type=int, default=128)
    parser.add_argument("--dilation", type=int, default=2)
    parser.add_argument("--min-face-fraction", type=float, default=0.01)
    parser.add_argument("--max-objects", type=int, default=16)
    parser.add_argument("--all-dynamic", action="store_true")
    args = parser.parse_args()
    if args.scale <= 0 or (args.target_max_dimension is not None and args.target_max_dimension <= 0):
        parser.error("scale and target-max-dimension must be positive")
    if not 48 <= args.voxel_resolution <= 256 or not 0 <= args.dilation <= 8:
        parser.error("voxel-resolution must be 48..256 and dilation must be 0..8")

    source = Path(args.input).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    output_dir = Path(args.output).expanduser().resolve()
    object_dir = output_dir / "objects"
    object_dir.mkdir(parents=True, exist_ok=True)

    import trimesh

    loaded = trimesh.load(str(source), force="scene")
    mesh = loaded.to_geometry() if isinstance(loaded, trimesh.Scene) else loaded
    if mesh is None or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError(f"No triangle mesh found in {source}")

    scale = float(args.scale)
    if args.target_max_dimension is not None:
        scale = float(args.target_max_dimension / max(mesh.extents))
    labels = [value.strip() for value in (args.labels or "").split(",") if value.strip()]
    origin = np.asarray(_parse_xyz(args.origin), dtype=float)
    face_groups, segmentation = _segment_faces(
        mesh,
        resolution=args.voxel_resolution,
        dilation=args.dilation,
        min_face_fraction=args.min_face_fraction,
        max_objects=args.max_objects,
    )
    face_groups.sort(key=len, reverse=True)
    global_floor_y = float(mesh.bounds[0][1])
    objects = []

    for index, face_indices in enumerate(face_groups):
        entity_mesh = mesh.submesh([face_indices], append=True, repair=False)
        bounds = np.asarray(entity_mesh.bounds, dtype=float)
        center = bounds.mean(axis=0)
        entity_mesh.apply_translation(-center)
        label = labels[index] if index < len(labels) else f"entity_{index + 1:02d}"
        object_id = _slug(label) or f"entity_{index + 1:02d}"
        if any(item["id"] == object_id for item in objects):
            object_id = f"{object_id}_{index + 1:02d}"
        asset_path = object_dir / f"{object_id}.glb"
        entity_mesh.export(str(asset_path))

        raw_extents = bounds[1] - bounds[0]
        dimensions = np.array([raw_extents[0], raw_extents[2], raw_extents[1]]) * scale
        relative = np.array([center[0], -center[2], center[1] - global_floor_y]) * scale
        position = origin + relative
        properties = _estimate_properties(dimensions)
        dynamic = bool(args.all_dynamic or index == 0)
        mass = float(properties["mass_kg"]["estimate"])
        friction = float(properties["friction"]["estimate"])
        if index == 0 and args.active_mass is not None:
            mass = float(args.active_mass)
            properties["mass_kg"].update(
                {"min": mass, "estimate": mass, "max": mass, "source": "user", "confidence": 1.0}
            )
        if index == 0 and args.active_friction is not None:
            friction = float(args.active_friction)
            properties["friction"].update(
                {
                    "min": friction,
                    "estimate": friction,
                    "max": friction,
                    "source": "user",
                    "confidence": 1.0,
                }
            )
        if index == 0 and args.active_mass is not None and args.active_friction is not None:
            properties["property_status"] = "calibrated"
        objects.append(
            {
                "id": object_id,
                "label": label,
                "source_path": str(asset_path.relative_to(output_dir)),
                "scale": scale,
                "position": position.tolist(),
                "orientation": [0.0, 0.0, 0.0, 1.0],
                "dynamic": dynamic,
                "mass_kg": mass,
                "friction": friction,
                "dimensions_m": dimensions.tolist(),
                "properties": properties,
                "segmentation": {
                    "face_count": int(len(face_indices)),
                    "face_fraction": float(len(face_indices) / len(mesh.faces)),
                    "confidence": float(segmentation["confidence"]),
                },
            }
        )

    active_id = objects[0]["id"]
    if args.active:
        requested = args.active.casefold()
        active_id = next(
            (
                item["id"]
                for item in objects
                if item["id"].casefold() == requested or item["label"].casefold() == requested
            ),
            active_id,
        )
    for item in objects:
        if item["id"] == active_id:
            item["dynamic"] = True

    manifest = {
        "format_version": MANIFEST_VERSION,
        "coordinate_system": "right-handed, Z-up, meters, quaternion XYZW",
        "source": {
            "model": str(source),
            "image": str(Path(args.source_image).expanduser().resolve()) if args.source_image else None,
        },
        "metric_calibration": {
            "scale": scale,
            "source": "target_max_dimension" if args.target_max_dimension else "user_or_model_units",
            "confidence": 1.0 if args.target_max_dimension else 0.5,
        },
        "segmentation": segmentation,
        "active_object_id": active_id,
        "objects": objects,
    }
    manifest_path = write_scene_manifest(output_dir / "scene_manifest.json", manifest)
    print(f"PREPARED_SCENE_MANIFEST={manifest_path}")
    print(f"PREPARED_SCENE_OBJECTS={len(objects)} active={active_id}")


def _segment_faces(mesh, resolution, dilation, min_face_fraction, max_objects):
    try:
        from scipy import ndimage
    except ImportError as exc:
        raise RuntimeError("Automatic scene splitting requires scipy") from exc

    lower = np.asarray(mesh.bounds[0], dtype=float)
    extent = np.asarray(mesh.extents, dtype=float)
    pitch = float(max(extent) / max(1, resolution - 1))
    shape = tuple((np.ceil(extent / pitch).astype(int) + 1).tolist())
    points = np.vstack((np.asarray(mesh.vertices), np.asarray(mesh.triangles_center)))
    indices = np.floor((points - lower) / pitch).astype(int)
    indices = np.clip(indices, 0, np.asarray(shape) - 1)
    occupancy = np.zeros(shape, dtype=bool)
    occupancy[tuple(indices.T)] = True
    if dilation:
        occupancy = ndimage.binary_dilation(occupancy, iterations=int(dilation))
    voxel_labels, count = ndimage.label(
        occupancy,
        structure=ndimage.generate_binary_structure(3, 3),
    )
    center_indices = np.floor((np.asarray(mesh.triangles_center) - lower) / pitch).astype(int)
    center_indices = np.clip(center_indices, 0, np.asarray(shape) - 1)
    face_labels = voxel_labels[tuple(center_indices.T)]
    labels, counts = np.unique(face_labels[face_labels > 0], return_counts=True)
    minimum_faces = max(50, int(len(mesh.faces) * max(0.0, min_face_fraction)))
    ranked = sorted(zip(labels.tolist(), counts.tolist()), key=lambda item: item[1], reverse=True)
    retained = [label for label, faces in ranked if faces >= minimum_faces][:max_objects]
    if not retained and ranked:
        retained = [ranked[0][0]]
    if not retained:
        return [np.arange(len(mesh.faces), dtype=int)], {
            "method": "single_mesh_fallback",
            "entity_count": 1,
            "voxel_pitch": pitch,
            "confidence": 0.25,
            "requires_review": True,
        }

    groups = {label: np.flatnonzero(face_labels == label) for label in retained}
    unassigned = np.flatnonzero(~np.isin(face_labels, retained))
    if len(unassigned) and groups:
        centers = np.asarray(mesh.triangles_center)
        group_centers = np.asarray([centers[value].mean(axis=0) for value in groups.values()])
        nearest = np.argmin(
            np.linalg.norm(centers[unassigned, None, :] - group_centers[None, :, :], axis=2),
            axis=1,
        )
        keys = list(groups)
        for group_index, key in enumerate(keys):
            groups[key] = np.concatenate((groups[key], unassigned[nearest == group_index]))

    result = [np.asarray(value, dtype=int) for value in groups.values()]
    shares = [len(value) / len(mesh.faces) for value in result]
    confidence = 0.9 if len(result) > 1 and min(shares) >= 0.08 else 0.65
    return result, {
        "method": "voxel_connectivity",
        "entity_count": len(result),
        "raw_component_count": int(count),
        "voxel_resolution": int(resolution),
        "voxel_pitch": pitch,
        "dilation_iterations": int(dilation),
        "confidence": confidence,
        "requires_review": confidence < 0.8,
    }


def _estimate_properties(dimensions):
    dimensions = np.maximum(np.asarray(dimensions, dtype=float), 1e-4)
    bbox_volume = float(np.prod(dimensions))
    estimate = float(np.clip(bbox_volume * 45.0, 0.05, 80.0))
    return {
        "mass_kg": {
            "min": max(0.02, estimate * 0.45),
            "estimate": estimate,
            "max": estimate * 2.2,
            "source": "geometry_prior",
            "confidence": 0.45,
        },
        "friction": {
            "min": 0.10,
            "estimate": 0.30,
            "max": 0.80,
            "source": "generic_surface_prior",
            "confidence": 0.35,
        },
        "property_status": "estimated",
        "simulation_only": True,
    }


def _parse_xyz(value):
    parts = [float(component.strip()) for component in str(value).split(",")]
    if len(parts) != 3:
        raise ValueError("origin must contain x,y,z")
    return parts


def _slug(value):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value).strip()).strip("_").lower()


if __name__ == "__main__":
    main()
