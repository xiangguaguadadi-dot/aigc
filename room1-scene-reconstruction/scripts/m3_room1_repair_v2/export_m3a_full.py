#!/usr/bin/env python3
"""Export the repaired room1 base mesh as the complete M3A metric scene."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import open3d as o3d
import pycolmap


ROOT = Path('/root/scene_recon')
BASE = ROOT / 'outputs/room1/m3_repair_v2/base'
MODEL = ROOT / 'outputs/room1/m3_repair_v2/model_planargs'
SRC_MESH = MODEL / 'mesh/tsdf_fusion_post.ply'
MEASURE = ROOT / 'outputs/room1/m3_repair_v2/review/sofa_metric_measurement.json'
OUT = ROOT / 'outputs/room1/m3_repair_v2/m3/full'


def transform_points(points: np.ndarray, origin: np.ndarray, x: np.ndarray,
                     y: np.ndarray, z: np.ndarray, scale: float) -> np.ndarray:
    centered = points - origin
    basis = np.column_stack((x, y, z))
    return (centered @ basis) * scale


def clean_mesh(mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
    mesh.remove_duplicated_vertices()
    mesh.remove_duplicated_triangles()
    mesh.remove_degenerate_triangles()
    mesh.remove_non_manifold_edges()
    mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    return mesh


def write_camera_poses(recon: pycolmap.Reconstruction, origin: np.ndarray,
                       x: np.ndarray, y: np.ndarray, z: np.ndarray,
                       scale: float) -> dict:
    basis = np.column_stack((x, y, z))
    poses = []
    for image in sorted(recon.images.values(), key=lambda item: item.name):
        cam_from_world = image.cam_from_world()
        r_cw = np.asarray(cam_from_world.rotation.matrix(), dtype=float)
        t_cw = np.asarray(cam_from_world.translation, dtype=float)
        # COLMAP camera center in the original world frame.
        center = -r_cw.T @ t_cw
        center_new = transform_points(center[None, :], origin, x, y, z, scale)[0]
        # New camera-to-world rotation: world_new = R_new * camera.
        r_new = (basis.T @ r_cw.T).T
        poses.append({
            'image': image.name,
            'camera_id': int(image.camera_id),
            'width': int(recon.cameras[image.camera_id].width),
            'height': int(recon.cameras[image.camera_id].height),
            'registered': bool(image.num_points2D() > 0),
            'center_m': center_new.tolist(),
            'camera_to_world_rotation': r_new.tolist(),
        })
    return {'scene_id': 'room1', 'coordinate_system': 'right_handed_Z_up_meters',
            'scale_m_per_colmap_unit': scale, 'poses': poses}


def sha256_files(paths: list[Path]) -> str:
    rows = []
    for path in sorted(paths):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f'{digest}  {path.name}')
    return '\n'.join(rows) + '\n'


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'renders').mkdir(exist_ok=True)
    measurement = json.loads(MEASURE.read_text())
    width_units = float(measurement['cluster_width_candidate_colmap_units'])
    if not np.isfinite(width_units) or width_units <= 0:
        raise ValueError(f'invalid sofa width: {width_units}')
    scale = 0.7 / width_units
    z = np.asarray(measurement['up_axis_colmap_world'], dtype=float)
    z /= np.linalg.norm(z)
    x = np.asarray(measurement['horizontal_pca_axes_colmap_world'][0], dtype=float)
    x -= z * np.dot(x, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    x /= np.linalg.norm(x)

    recon = pycolmap.Reconstruction(str(BASE / 'sparse_fast_v3'))
    mesh = clean_mesh(o3d.io.read_triangle_mesh(str(SRC_MESH)))
    if len(mesh.vertices) == 0 or len(mesh.triangles) == 0:
        raise RuntimeError('source TSDF mesh is empty')
    points = np.asarray(mesh.vertices)
    # Center on the source mesh centroid; this keeps metric coordinates compact.
    origin = points.mean(axis=0)
    mesh.vertices = o3d.utility.Vector3dVector(transform_points(points, origin, x, y, z, scale))
    mesh.compute_vertex_normals()
    mesh = clean_mesh(mesh)
    scene_ply = OUT / 'static_scene_full.ply'
    scene_glb = OUT / 'static_scene_full.glb'
    o3d.io.write_triangle_mesh(str(scene_ply), mesh, write_ascii=False)
    o3d.io.write_triangle_mesh(str(scene_glb), mesh, write_ascii=False)

    collision = mesh.simplify_quadric_decimation(target_number_of_triangles=min(200000, len(mesh.triangles)))
    collision = clean_mesh(collision)
    collision_ply = OUT / 'static_collision_full.ply'
    o3d.io.write_triangle_mesh(str(collision_ply), collision, write_ascii=False)
    collision_path = OUT / 'static_collision_full.glb'
    o3d.io.write_triangle_mesh(str(collision_path), collision, write_ascii=False)

    sofa_report = {
        'scene_id': 'room1',
        'anchor': 'gray_sofa_outer_armrest_to_outer_armrest',
        'original_width_colmap_units': width_units,
        'target_width_m': 0.7,
        'scale_factor_m_per_colmap_unit': scale,
        'calibrated_width_m': width_units * scale,
        'relative_error': abs(width_units * scale - 0.7) / 0.7,
        'measurement_source': str(MEASURE),
        'measurement_cluster_points': measurement['dbscan_largest_cluster_points'],
        'origin_colmap_world': origin.tolist(),
        'x_axis_colmap_world': x.tolist(),
        'y_axis_colmap_world': y.tolist(),
        'z_axis_colmap_world': z.tolist(),
    }
    (OUT / 'scale_calibration.json').write_text(json.dumps(sofa_report, indent=2) + '\n')
    poses = write_camera_poses(recon, origin, x, y, z, scale)
    (OUT / 'camera_poses.json').write_text(json.dumps(poses, indent=2) + '\n')
    manifest = {
        'scene_id': 'room1', 'variant': 'M3A_full',
        'source_mesh': str(SRC_MESH), 'source_registered_images': 211,
        'source_keyframes': 265, 'preserved_static_objects': True,
        'removed_instances': [], 'coordinate_system': 'right_handed_Z_up_meters',
        'mesh': {'vertices': len(mesh.vertices), 'triangles': len(mesh.triangles)},
        'collision_mesh': {'vertices': len(collision.vertices), 'triangles': len(collision.triangles)},
        'scale_calibration': sofa_report,
    }
    (OUT / 'scene_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    files = [scene_glb, scene_ply, collision_path, OUT / 'camera_poses.json',
             OUT / 'scale_calibration.json', OUT / 'scene_manifest.json']
    (OUT / 'checksums.sha256').write_text(sha256_files(files))
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
