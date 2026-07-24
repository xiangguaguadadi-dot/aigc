"""
Engineering-Grade Mesh & Physics Processing.

Implements the key steps from the engineering manual:
  1. Scale Calibration — use a known reference object to get real-world scale
  2. Watertight Meshing — ManifoldPlus-style repair
  3. Compound Collision — VHACD multi-convex-hull decomposition
  4. Physics Auto-Assignment — apply material → density/friction/restitution from LUT
"""

import numpy as np
from typing import Optional, Tuple, List, Dict
import warnings


# ===========================================================================
# 1. Scale Calibration
# ===========================================================================

# Known real-world reference sizes (meters)
REFERENCE_SIZES = {
    "door":    2.00,   # standard door height
    "doorframe": 2.00,
    "A4_paper": 0.21,  # A4 width
    "ceiling":  2.60,   # standard ceiling height (China)
    "floor_tile": 0.60, # common tile size
    "person":   1.70,   # average human height
    "chair_seat": 0.45, # standard chair seat height
    "table":    0.75,   # standard table height
    "sofa":     0.85,   # sofa seat height
    "tv_55inch": 1.22,  # 55" TV width
    "laptop_15": 0.34,  # 15" laptop width
    "cup":      0.08,   # typical cup diameter
    "bottle_500ml": 0.07,
}

def calibrate_scale(
    reference_label: str,
    mesh_bbox_diagonal: float,
    custom_size_m: Optional[float] = None,
) -> float:
    """
    Compute scale factor: real_size / mesh_size.
    Uses reference size table or category estimation.
    """
    real_size = custom_size_m or REFERENCE_SIZES.get(reference_label.lower())
    if real_size is None:
        # Category-based fallback
        _cat_sizes = {
            "chair": 0.50, "apple": 0.08, "cup": 0.08, "table": 0.80,
            "sofa": 2.0, "laptop": 0.35, "book": 0.20, "bottle": 0.07,
        }
        real_size = _cat_sizes.get(reference_label.lower(), 0.30)

    if mesh_bbox_diagonal < 1e-6:
        return 1.0
    return real_size / mesh_bbox_diagonal


def apply_scale(
    vertices: np.ndarray,
    scale_factor: float,
    faces: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Scale mesh vertices to real-world meters. APPLY SCALE (not just note it)."""
    return vertices.astype(np.float64) * scale_factor, faces


# ===========================================================================
# 2. Watertight Meshing (ManifoldPlus-style)
# ===========================================================================

def make_watertight(
    vertices: np.ndarray,
    faces: np.ndarray,
    method: str = "auto",
    depth: int = 8,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Repair mesh to be watertight (closed manifold).

    Methods (tried in order if "auto"):
      1. trimesh.fill_holes + fix_normals (fast, preserves topology)
      2. Poisson surface reconstruction (guaranteed watertight, may lose detail)
      3. Convex hull (last resort)

    Returns (vertices, faces) of watertight mesh.
    """
    if len(faces) == 0 or len(vertices) == 0:
        return vertices, faces

    import trimesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)

    # Already watertight?
    if mesh.is_watertight:
        return vertices, faces

    # ---- Method 1: Fill holes ----
    try:
        mesh.fill_holes()
        mesh.remove_degenerate_faces()
        mesh.remove_duplicate_faces()
        mesh.remove_unreferenced_vertices()
        if mesh.is_watertight:
            return mesh.vertices.astype(np.float32), mesh.faces.astype(np.int32)
    except Exception:
        pass

    # ---- Method 2: Poisson reconstruction ----
    if method in ("auto", "poisson"):
        try:
            import open3d as o3d
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(vertices)
            bbox_diag = np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0))
            pcd.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(
                    radius=bbox_diag * 0.05, max_nn=50
                )
            )
            pcd.orient_normals_consistent_tangent_plane(k=50)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                poisson_mesh, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                    pcd, depth=depth, scale=1.1
                )
            poisson_mesh.remove_degenerate_triangles()
            poisson_mesh.remove_duplicated_vertices()
            poisson_mesh.remove_unreferenced_vertices()

            if len(poisson_mesh.vertices) > 0:
                return (
                    np.asarray(poisson_mesh.vertices).astype(np.float32),
                    np.asarray(poisson_mesh.triangles).astype(np.int32),
                )
        except Exception:
            pass

    # ---- Method 3: Convex hull ----
    try:
        hull = trimesh.convex.convex_hull(mesh)
        if hull is not None:
            return hull.vertices.astype(np.float32), hull.faces.astype(np.int32)
    except Exception:
        pass

    # Give up, return original
    return vertices, faces


# ===========================================================================
# 3. Compound Collision (VHACD decomposition)
# ===========================================================================

def generate_compound_collision(
    vertices: np.ndarray,
    faces: np.ndarray,
    max_convex_hulls: int = 8,
    max_faces_per_hull: int = 64,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Decompose mesh into multiple convex hulls for better collision accuracy.

    Returns list of (hull_vertices, hull_faces) tuples.
    """
    if len(faces) == 0 or len(vertices) == 0:
        return []

    import trimesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)

    try:
        # VHACD decomposition (trimesh built-in)
        hulls = mesh.convex_decomposition(
            maxhulls=max_convex_hulls,
            maxNumVerticesPerCH=max_faces_per_hull,
        )
        if isinstance(hulls, list) and len(hulls) > 0:
            result = []
            for h in hulls:
                if hasattr(h, 'vertices') and len(h.vertices) > 3:
                    result.append((
                        h.vertices.astype(np.float32),
                        h.faces.astype(np.int32),
                    ))
            if result:
                return result
    except Exception:
        pass

    # Fallback: single convex hull
    try:
        hull = trimesh.convex.convex_hull(mesh)
        if hull is not None and len(hull.vertices) > 3:
            return [(hull.vertices.astype(np.float32), hull.faces.astype(np.int32))]
    except Exception:
        pass

    # Last resort: oriented bounding box as 12-triangle box
    return [_obb_as_mesh(vertices)]


def _obb_as_mesh(vertices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Generate an oriented bounding box mesh."""
    try:
        import open3d as o3d
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(vertices)
        obb = pcd.get_oriented_bounding_box()
        box_mesh = o3d.geometry.TriangleMesh.create_from_oriented_bounding_box(obb)
        return (
            np.asarray(box_mesh.vertices).astype(np.float32),
            np.asarray(box_mesh.triangles).astype(np.int32),
        )
    except Exception:
        # Axis-aligned box
        bmin = vertices.min(axis=0)
        bmax = vertices.max(axis=0)
        corners = np.array([
            [bmin[0], bmin[1], bmin[2]], [bmax[0], bmin[1], bmin[2]],
            [bmax[0], bmax[1], bmin[2]], [bmin[0], bmax[1], bmin[2]],
            [bmin[0], bmin[1], bmax[2]], [bmax[0], bmin[1], bmax[2]],
            [bmax[0], bmax[1], bmax[2]], [bmin[0], bmax[1], bmax[2]],
        ])
        tris = np.array([
            [0,1,2],[0,2,3],[4,5,6],[4,6,7],
            [0,1,5],[0,5,4],[2,3,7],[2,7,6],
            [0,3,7],[0,7,4],[1,2,6],[1,6,5],
        ])
        return corners.astype(np.float32), tris.astype(np.int32)


# ===========================================================================
# 4. Physics Auto-Assignment
# ===========================================================================

def auto_assign_physics(
    label: str,
    vertices: np.ndarray,
    faces: np.ndarray,
    scale_m: float = 1.0,
    material_override: Optional[str] = None,
) -> Dict:
    """
    Auto-assign all physical properties to a mesh.

    Returns dict ready for M3/M4 consumption:
      {material, density, mass_kg, friction, restitution,
       watertight_vertices, watertight_faces,
       collision_hulls: [(v,f), ...],
       scale_m, volume_m3}
    """
    from pipeline.module3_physics.material import (
        _default_properties, MATERIAL_DENSITY, MATERIAL_FRICTION, MATERIAL_RESTITUTION
    )
    from pipeline.module3_physics.physics import compute_mesh_volume

    props = _default_properties(label)
    if material_override:
        props["material"] = material_override

    material = props["material"]

    # --- 1. Apply Scale (CRITICAL step from manual) ---
    scaled_verts = vertices.astype(np.float64) * scale_m

    # --- 2. Watertight ---
    wt_verts, wt_faces = make_watertight(scaled_verts, faces, method="auto")

    # --- 3. Volume & Mass ---
    vol_m3 = compute_mesh_volume(wt_verts, wt_faces)
    density = MATERIAL_DENSITY.get(material, 1000)
    mass = vol_m3 * density

    # --- 4. Compound Collision ---
    collision_hulls = generate_compound_collision(wt_verts, wt_faces)

    return {
        "material": material,
        "density_kg_m3": density,
        "mass_kg": mass,
        "friction": MATERIAL_FRICTION.get(material, 0.4),
        "restitution": MATERIAL_RESTITUTION.get(material, 0.1),
        "volume_m3": vol_m3,
        "scale_m": scale_m,
        "watertight_vertices": wt_verts,
        "watertight_faces": wt_faces,
        "collision_hulls": collision_hulls,
        "num_hulls": len(collision_hulls),
    }
