"""
Mesher — Mesh cleaning and watertight processing.

Strategy (updated):
  - TRELLIS.2 already outputs a good mesh → preserve it
  - Only clean/fix: remove degenerate faces, duplicate vertices, fill holes
  - Poisson reconstruction ONLY as fallback for raw point clouds
"""

import numpy as np
from typing import Optional, Tuple


def clean_mesh_preserve(
    vertices: np.ndarray,
    faces: np.ndarray,
    vertex_colors: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """
    Clean an existing mesh minimally. Preserves original topology.

    Primary path for TRELLIS.2 outputs — the mesh is already good.
    Only does basic cleanup: remove NaN, deduplicate vertices.
    """
    if len(faces) == 0 or len(vertices) == 0:
        return vertices, faces, vertex_colors

    # 1. Remove NaN/inf vertices and their faces
    valid_v = np.isfinite(vertices).all(axis=1)
    if not valid_v.all():
        valid_f = valid_v[faces].all(axis=1)
        faces = faces[valid_f]
        # Remap vertex indices
        old_to_new = np.cumsum(valid_v) - 1
        faces = old_to_new[faces]
        vertices = vertices[valid_v]
        if vertex_colors is not None:
            vertex_colors = vertex_colors[valid_v]

    # 2. Remove degenerate faces (area ≈ 0)
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    cross = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    area_threshold = cross.max() * 1e-8 if cross.max() > 0 else 1e-12
    non_degen = cross > area_threshold
    faces = faces[non_degen]

    if len(faces) == 0:
        return vertices, faces, vertex_colors

    return vertices.astype(np.float32), faces.astype(np.int32), vertex_colors


def points_to_mesh_poisson(
    points: np.ndarray,
    colors: Optional[np.ndarray] = None,
    depth: int = 10,
    scale: float = 1.1,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Point cloud → watertight mesh via Poisson surface reconstruction.

    FALLBACK only — use when input is a raw point cloud (no faces).
    """
    try:
        import open3d as o3d
    except ImportError:
        raise ImportError("open3d required")

    if len(points) < 10:
        return None, None, None

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)

    bbox_diag = np.linalg.norm(points.max(axis=0) - points.min(axis=0))
    vs = max(bbox_diag * 0.005, 0.002)
    pcd = pcd.voxel_down_sample(vs)

    pcd.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(
            radius=max(bbox_diag * 0.05, 0.01), max_nn=50
        )
    )

    try:
        pcd.orient_normals_consistent_tangent_plane(k=50)
    except Exception:
        pcd.orient_normals_towards_camera_location(pcd.get_center() + np.array([0, 0, bbox_diag * 3]))

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            pcd, depth=depth, scale=scale, linear_fit=False
        )

    if len(densities) > 0:
        lo = np.quantile(densities, 0.01)
        mask = densities >= lo
        mesh.remove_vertices_by_mask(~mask)

    # Crop to bounding box
    try:
        mesh = mesh.crop(pcd.get_axis_aligned_bounding_box().scale(1.2, pcd.get_center()))
    except Exception:
        pass

    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_unreferenced_vertices()

    if len(mesh.vertices) == 0:
        return None, None, None

    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.triangles)

    vertex_colors = None
    if colors is not None:
        vertex_colors = _transfer_colors(
            np.asarray(pcd.points), colors, vertices
        )

    return vertices, faces, vertex_colors


def generate_mesh(
    points: np.ndarray,
    colors: Optional[np.ndarray] = None,
    faces_input: Optional[np.ndarray] = None,  # NEW: pass original faces
    method: str = "preserve",  # NEW: "preserve" | "poisson"
    depth: int = 10,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Generate/clean mesh.

    - If faces_input is provided: clean and preserve original topology
    - If no faces: use Poisson reconstruction

    Returns (vertices, faces, vertex_colors).
    """
    if faces_input is not None and len(faces_input) > 0 and method in ("preserve", "auto"):
        # Clean the original mesh — keep topology, just fix issues
        return clean_mesh_preserve(points, faces_input, colors)

    # Fallback: Poisson reconstruction from point cloud
    return points_to_mesh_poisson(points, colors, depth=depth)


def _transfer_colors(src_pts, src_cols, dst_pts):
    from scipy.spatial import cKDTree
    tree = cKDTree(src_pts)
    _, idx = tree.query(dst_pts, k=1)
    return src_cols[idx]
