"""
Spec-Compliant Module 2: AI Perception → Structured Physics Properties

Output EXACTLY matches the requirement doc's JSON schema.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
import json


# ===========================================================================
# §Module 2 Requirements: Material parameters from engineering handbook
# ===========================================================================

MATERIAL_DB = {
    "wood": {
        "density": 700, "static_friction": 0.55, "dynamic_friction": 0.48,
        "restitution": 0.30, "young_modulus": 1.1e10, "is_deformable": False,
    },
    "metal": {
        "density": 7800, "static_friction": 0.40, "dynamic_friction": 0.35,
        "restitution": 0.15, "young_modulus": 2.0e11, "is_deformable": False,
    },
    "ceramic": {
        "density": 2400, "static_friction": 0.42, "dynamic_friction": 0.38,
        "restitution": 0.08, "young_modulus": 7.0e10, "is_deformable": False,
    },
    "plastic": {
        "density": 1200, "static_friction": 0.35, "dynamic_friction": 0.30,
        "restitution": 0.40, "young_modulus": 2.5e9, "is_deformable": False,
    },
    "fabric": {
        "density": 300, "static_friction": 0.65, "dynamic_friction": 0.60,
        "restitution": 0.05, "young_modulus": 1.0e7, "is_deformable": True,
    },
    "glass": {
        "density": 2500, "static_friction": 0.25, "dynamic_friction": 0.20,
        "restitution": 0.10, "young_modulus": 7.0e10, "is_deformable": False,
    },
    "leather": {
        "density": 860, "static_friction": 0.50, "dynamic_friction": 0.45,
        "restitution": 0.20, "young_modulus": 1.0e8, "is_deformable": False,
    },
    "stone": {
        "density": 2700, "static_friction": 0.60, "dynamic_friction": 0.55,
        "restitution": 0.05, "young_modulus": 5.0e10, "is_deformable": False,
    },
    "rubber": {
        "density": 1100, "static_friction": 0.80, "dynamic_friction": 0.75,
        "restitution": 0.70, "young_modulus": 1.0e7, "is_deformable": True,
    },
    "organic": {
        "density": 1000, "static_friction": 0.45, "dynamic_friction": 0.40,
        "restitution": 0.10, "young_modulus": 1.0e8, "is_deformable": False,
    },
}


@dataclass
class PhysicsParams:
    """Matches the requirement doc's physical_params schema."""
    density: float
    static_friction: float
    dynamic_friction: float
    restitution: float
    young_modulus: float
    is_deformable: bool


@dataclass
class GeometryParams:
    """Matches the requirement doc's geometry_params schema."""
    volume: float          # m³
    mass: float            # kg
    bounding_box: List[float]  # [lx, ly, lz] meters
    center_position: List[float]  # [x, y, z] world coords


@dataclass
class ObjectProperties:
    """FULL spec-compliant output per object (§Module 2)."""
    object_id: str
    category: str
    material: str
    confidence: float
    physical_params: Dict
    geometry_params: Dict
    spatial_relation: List[str] = field(default_factory=list)
    interactable: bool = True
    static: bool = False


def infer_properties(
    object_id: str,
    vertices: np.ndarray,
    faces: np.ndarray,
    material: str,
    confidence: float = 0.85,
    scale_m: float = 1.0,
    world_position: Optional[np.ndarray] = None,
    spatial_relations: Optional[List[str]] = None,
) -> ObjectProperties:
    """
    Compute FULL spec-compliant property dict from mesh + material.

    This is the definitive function matching the requirement document §Module 2.
    """
    from pipeline.module3_physics.physics import compute_mesh_volume

    # 1. Scale to meters
    scaled_v = vertices.astype(np.float64) * scale_m

    # 2. Material lookup
    mat_db = MATERIAL_DB.get(material.lower(), MATERIAL_DB["plastic"])

    # 3. Volume & Mass
    volume_m3 = compute_mesh_volume(scaled_v, faces)
    if volume_m3 < 1e-12:
        volume_m3 = 1e-6  # minimum 1 cm³ for tiny objects
    mass_kg = volume_m3 * mat_db["density"]

    # 4. Bounding box
    bmin = scaled_v.min(axis=0)
    bmax = scaled_v.max(axis=0)
    bbox = (bmax - bmin).tolist()

    # 5. Center position (world coords)
    if world_position is None:
        center_pos = ((bmin + bmax) / 2).tolist()
    else:
        center_pos = world_position.tolist()

    # 6. Category mapping
    category = f"{material}_{object_id.split('_')[0] if '_' in object_id else object_id}"

    # 7. Interactable/static
    is_static = material in ("wall", "floor", "ceiling", "ground")
    is_interactable = not is_static

    # Build spec-compliant object
    return ObjectProperties(
        object_id=object_id,
        category=category,
        material=material,
        confidence=min(confidence, 1.0),
        physical_params={
            "density": mat_db["density"],
            "static_friction": mat_db["static_friction"],
            "dynamic_friction": mat_db["dynamic_friction"],
            "restitution": mat_db["restitution"],
            "young_modulus": mat_db["young_modulus"],
            "is_deformable": mat_db["is_deformable"],
        },
        geometry_params={
            "volume": volume_m3,
            "mass": mass_kg,
            "bounding_box": bbox,
            "center_position": center_pos,
        },
        spatial_relation=spatial_relations or [],
        interactable=is_interactable,
        static=is_static,
    )


def to_spec_json(obj: ObjectProperties) -> dict:
    """Convert to the EXACT JSON format from the requirement doc."""
    return {
        "object_id": obj.object_id,
        "category": obj.category,
        "material": obj.material,
        "confidence": obj.confidence,
        "physical_params": obj.physical_params,
        "geometry_params": obj.geometry_params,
        "spatial_relation": obj.spatial_relation,
        "interactable": obj.interactable,
        "static": obj.static,
    }


# ===========================================================================
# Demo: Generate spec-compliant output for our 3 test objects
# ===========================================================================

def demo_spec():
    """Generate requirement-doc-format JSON for all objects."""
    import trimesh, os

    objects = [
        ("chair_000", "/root/trellis2-pipeline/output_chair.glb", "wood",   0.3426, 0.92),
        ("apple_001","/root/trellis2-pipeline/output_apple.glb","organic", 0.0477, 0.88),
        ("cup_002",  "/root/trellis2-pipeline/output_3.glb",     "ceramic", 0.0786, 0.90),
    ]

    results = []
    for obj_id, glb_path, material, scale, conf in objects:
        if not os.path.exists(glb_path):
            continue
        mesh = trimesh.load(glb_path)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_geometry()

        props = infer_properties(
            object_id=obj_id,
            vertices=mesh.vertices,
            faces=mesh.faces,
            material=material,
            confidence=conf,
            scale_m=scale,
            spatial_relations=[f"on_floor"]
        )
        results.append(to_spec_json(props))

    # Print in requirement doc format
    print(json.dumps(results, indent=2, ensure_ascii=False))

    # Save
    out = "/root/trellis2-pipeline/spec_output.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out}")
    return results


if __name__ == "__main__":
    demo_spec()
