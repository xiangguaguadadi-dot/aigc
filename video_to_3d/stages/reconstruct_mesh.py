"""Stage 6: Reconstruct mesh from fused point cloud using TSDF / Poisson."""

import numpy as np
from pathlib import Path

from video_to_3d.utils.io import save_pointcloud_ply, save_mesh
from video_to_3d.utils.validation import check_point_cloud, check_mesh


def run(
    point_cloud: np.ndarray,
    output_dir: Path,
    target_face_count: int = 50000,
    voxel_size_ratio: float = 0.008,
) -> dict:
    """Reconstruct a watertight mesh from a point cloud.

    Uses Open3D's TSDF integration pipeline (volumetric fusion via
    `create_from_point_cloud_poisson`) with optional simplification.

    Strategy:
        1. Estimate normals from the point cloud
        2. Orient normals consistently (toward camera; approximated via centroid)
        3. Poisson surface reconstruction
        4. Mesh cleanup: remove small components, fill holes
        5. Decimate to target face count

    Args:
        point_cloud: (N, 3) array of fused points
        output_dir: Base output directory
        target_face_count: Target number of faces after decimation
        voxel_size_ratio: Voxel size as ratio of scene diagonal (for normal estimation)

    Returns:
        dict with mesh paths and summary
    """
    import open3d as o3d

    mesh_dir = output_dir / "mesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)

    check_point_cloud(point_cloud, "Input point cloud")

    extent = float(np.ptp(point_cloud, axis=0).max())
    voxel_size = extent * voxel_size_ratio if extent > 0 else 0.01

    print(f"Reconstructing surface from {point_cloud.shape[0]} points...")
    print(f"  Scene extent: {extent:.3f}, voxel_size: {voxel_size:.6f}")

    # Create Open3D point cloud
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(point_cloud)

    # Estimate normals
    pcd.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(
            radius=voxel_size * 10, max_nn=30
        )
    )

    # Orient normals toward the centroid (approximate outward-facing)
    pcd.orient_normals_towards_camera_location(
        camera_location=np.mean(point_cloud, axis=0)
    )
    # Actually, orient_normals_towards_camera_location expects a camera position.
    # For a centered object, orient outward from centroid:
    centroid = point_cloud.mean(axis=0)
    pcd.orient_normals_towards_camera_location(camera_location=centroid * 2)

    # Poisson reconstruction
    print("  Running Poisson surface reconstruction...")
    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pcd, depth=9, width=0, scale=1.1, linear_fit=False
    )
    print(f"  Poisson mesh: {len(mesh.vertices)} vertices, {len(mesh.triangles)} faces")

    # Remove low-density vertices (only the very lowest 1% — preserves thin structures)
    densities_np = np.asarray(densities)
    density_cutoff = np.percentile(densities_np, 1)  # remove bottom 1% only
    if len(densities_np) == len(mesh.vertices):
        vertices_to_remove = densities_np < density_cutoff
        mesh.remove_vertices_by_mask(vertices_to_remove)
        print(f"  After density filter: {len(mesh.vertices)} vertices, {len(mesh.triangles)} faces")
    else:
        print(f"  WARNING: density array size mismatch ({len(densities_np)} vs {len(mesh.vertices)}), skipping filter")

    mesh = mesh.remove_duplicated_vertices()
    mesh = mesh.remove_degenerate_triangles()

    # Keep all significant components (not just the largest)
    # This preserves thin structures like cup handles that form separate components
    comp_idx = mesh.cluster_connected_triangles()
    comp_labels = np.array(comp_idx[0])
    comp_counts = np.bincount(comp_labels)
    largest_count = comp_counts.max()
    min_component_size = largest_count * 0.05  # keep components > 5% of largest
    keep_labels = set(np.where(comp_counts >= min_component_size)[0])
    triangles_to_keep = np.array([l in keep_labels for l in comp_labels])
    mesh.remove_triangles_by_mask(~triangles_to_keep)
    mesh.remove_unreferenced_vertices()
    print(f"  Components kept: {len(keep_labels)}/{len(comp_counts)} "
          f"({len(mesh.vertices)} vertices, {len(mesh.triangles)} faces)")

    # Decimate to target face count
    if len(mesh.triangles) > target_face_count:
        print(f"  Decimating to ~{target_face_count} faces...")
        mesh = mesh.simplify_quadric_decimation(target_face_count)
        print(f"  After decimation: {len(mesh.vertices)} vertices, {len(mesh.triangles)} faces")

    # Ensure mesh is manifold
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_non_manifold_edges()

    # Convert to trimesh for export
    import trimesh
    tm = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices),
        faces=np.asarray(mesh.triangles),
    )

    # Check result
    check_mesh(tm, "Reconstructed mesh")

    # Save
    mesh_path = mesh_dir / "reconstructed.ply"
    save_mesh(tm, mesh_path)

    # Report
    mesh_info = {
        "vertices": len(tm.vertices),
        "faces": len(tm.faces),
        "is_watertight": tm.is_watertight,
        "bounding_box": {
            "min": tm.bounds[0].tolist(),
            "max": tm.bounds[1].tolist(),
        },
    }

    import json
    with open(mesh_dir / "mesh_report.json", "w") as f:
        json.dump(mesh_info, f, indent=2)

    print(f"Surface reconstruction complete: {mesh_info['faces']} faces, "
          f"watertight={mesh_info['is_watertight']}")

    result = {
        "mesh_path": str(mesh_path.relative_to(output_dir)),
        "mesh": tm,
        "mesh_info": mesh_info,
    }

    return result
