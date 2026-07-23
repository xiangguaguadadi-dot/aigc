#!/usr/bin/env bash
set -euo pipefail
PY=/root/scene_recon/tools/micromamba-root/envs/planargs/bin/python
$PY - <<'PY'
import json
from pathlib import Path
import open3d as o3d
import numpy as np

root = Path('/root/scene_recon/outputs/room1/m3_repair_v2/model_planargs/mesh')
for path in sorted(root.glob('*.ply')):
    mesh = o3d.io.read_triangle_mesh(str(path), enable_post_processing=False)
    mesh.remove_duplicated_vertices()
    mesh.remove_duplicated_triangles()
    mesh.remove_degenerate_triangles()
    mesh.remove_unreferenced_vertices()
    bbox = mesh.get_axis_aligned_bounding_box()
    labels, counts, _ = mesh.cluster_connected_triangles()
    counts = np.asarray(counts)
    print(json.dumps({
        'path': str(path),
        'vertices': len(mesh.vertices),
        'triangles': len(mesh.triangles),
        'components': len(counts),
        'largest_component_triangles': int(counts.max()) if len(counts) else 0,
        'largest_component_ratio': float(counts.max() / len(labels)) if len(labels) else 0.0,
        'bbox_min': list(bbox.min_bound),
        'bbox_max': list(bbox.max_bound),
    }))
PY
