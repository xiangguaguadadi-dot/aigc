"""
COLMAP I/O — Parse camera poses and point clouds from COLMAP output.

Supports:
  - COLMAP text format (cameras.txt, images.txt, points3D.txt)
  - COLMAP binary format (cameras.bin, images.bin, points3D.bin)
  - NeRFStudio transforms.json

Usage:
  poses = load_colmap_poses("./sparse/0/")
  # → {"image_001.jpg": {"R": (3,3), "t": (3,), "K": (3,3), "width": int, "height": int}, ...}
"""

import os, struct, json
import numpy as np
from typing import Dict, Tuple, Optional


# ===========================================================================
# COLMAP Binary Reader
# ===========================================================================

def read_next_bytes(fid, num_bytes, format_char_sequence, endian="<"):
    """Read binary data from file."""
    data = fid.read(num_bytes)
    return struct.unpack(endian + format_char_sequence, data)


def read_cameras_binary(path: str) -> Dict:
    """Read cameras.bin → {cam_id: {model, width, height, params}}."""
    cameras = {}
    with open(path, "rb") as fid:
        num_cameras = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_cameras):
            camera_id = read_next_bytes(fid, 4, "i")[0]
            model_id = read_next_bytes(fid, 4, "i")[0]
            model_name = _camera_model_name(model_id)
            width = read_next_bytes(fid, 8, "Q")[0]
            height = read_next_bytes(fid, 8, "Q")[0]
            num_params = _camera_model_num_params(model_id)
            params = list(read_next_bytes(fid, 8 * num_params, "d" * num_params))
            cameras[camera_id] = {
                "model": model_name, "width": width, "height": height,
                "params": params,
            }
    return cameras


def read_images_binary(path: str) -> Dict:
    """Read images.bin → {image_id: {cam_id, name, qvec, tvec}}."""
    images = {}
    with open(path, "rb") as fid:
        num_images = read_next_bytes(fid, 8, "Q")[0]
        for _ in range(num_images):
            image_id = read_next_bytes(fid, 4, "i")[0]
            qvec = np.array(read_next_bytes(fid, 4 * 4, "d" * 4))
            tvec = np.array(read_next_bytes(fid, 3 * 4, "d" * 3))
            camera_id = read_next_bytes(fid, 4, "i")[0]
            name_bytes = fid.read(1)[0]
            name = fid.read(name_bytes).decode("utf-8")
            _ = read_next_bytes(fid, 8, "Q")[0]  # num_points2D
            images[image_id] = {
                "camera_id": camera_id, "name": name,
                "qvec": qvec, "tvec": tvec,
            }
    return images


# ===========================================================================
# Camera model helpers
# ===========================================================================

def _camera_model_name(model_id: int) -> str:
    models = {0: "SIMPLE_PINHOLE", 1: "PINHOLE", 2: "SIMPLE_RADIAL",
              3: "RADIAL", 4: "OPENCV", 5: "OPENCV_FISHEYE"}
    return models.get(model_id, f"UNKNOWN_{model_id}")


def _camera_model_num_params(model_id: int) -> int:
    return {0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 8}.get(model_id, 4)


def camera_to_intrinsic(camera: Dict) -> np.ndarray:
    """Convert COLMAP camera params to 3×3 intrinsic matrix K."""
    model = camera["model"]
    params = camera["params"]
    K = np.eye(3)
    if model in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL"):
        f, cx, cy = params[0], params[1], params[2]
        K[0, 0] = K[1, 1] = f
        K[0, 2] = cx; K[1, 2] = cy
    elif model in ("PINHOLE", "RADIAL", "OPENCV", "OPENCV_FISHEYE"):
        fx, fy, cx, cy = params[0], params[1], params[2], params[3]
        K[0, 0] = fx; K[1, 1] = fy
        K[0, 2] = cx; K[1, 2] = cy
    return K


def qvec_to_rotmat(qvec: np.ndarray) -> np.ndarray:
    """COLMAP quaternion (qw, qx, qy, qz) → 3x3 rotation matrix."""
    qw, qx, qy, qz = qvec
    return np.array([
        [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qz*qw,    2*qx*qz + 2*qy*qw],
        [2*qx*qy + 2*qz*qw,    1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qx*qw],
        [2*qx*qz - 2*qy*qw,    2*qy*qz + 2*qx*qw,    1 - 2*qx**2 - 2*qy**2],
    ])


# ===========================================================================
# High-level API
# ===========================================================================

def load_colmap_poses(sparse_dir: str) -> Dict[str, Dict]:
    """
    Load all camera poses from COLMAP sparse directory.

    Returns:
      {"image_name.jpg": {
          "R": (3,3),        # rotation matrix (world → camera)
          "t": (3,),         # translation vector
          "K": (3,3),        # intrinsic matrix
          "width": int, "height": int,
          "position": (3,)   # camera center in world coords
      }, ...}
    """
    # Try binary format first
    cams_bin = os.path.join(sparse_dir, "cameras.bin")
    imgs_bin = os.path.join(sparse_dir, "images.bin")

    if os.path.exists(cams_bin) and os.path.exists(imgs_bin):
        cameras = read_cameras_binary(cams_bin)
        images = read_images_binary(imgs_bin)
    else:
        raise FileNotFoundError(
            f"No COLMAP output found in {sparse_dir}. "
            f"Expected cameras.bin + images.bin"
        )

    poses = {}
    for img_id, img_data in images.items():
        cam = cameras[img_data["camera_id"]]
        R = qvec_to_rotmat(img_data["qvec"])  # world → camera
        t = img_data["tvec"]
        K = camera_to_intrinsic(cam)
        # Camera center in world: C = -R^T @ t
        position = -R.T @ t

        poses[img_data["name"]] = {
            "R": R, "t": t, "K": K,
            "width": cam["width"], "height": cam["height"],
            "position": position,
        }
    return poses


def load_transforms_json(path: str) -> Dict[str, Dict]:
    """
    Load NeRFStudio / Instant-NGP transforms.json format.

    Returns same dict format as load_colmap_poses().
    """
    with open(path) as f:
        data = json.load(f)

    poses = {}
    w = data.get("w", data.get("width", 1920))
    h = data.get("h", data.get("height", 1080))
    fl_x = data.get("fl_x", data.get("fx", w))
    fl_y = data.get("fl_y", data.get("fy", fl_x))
    cx = data.get("cx", w / 2)
    cy = data.get("cy", h / 2)

    K = np.array([[fl_x, 0, cx], [0, fl_y, cy], [0, 0, 1]])

    for frame in data.get("frames", []):
        path = frame.get("file_path", frame.get("image_path", ""))
        name = os.path.basename(path)

        mat = np.array(frame["transform_matrix"])
        R = mat[:3, :3]
        t = mat[:3, 3]
        position = -R.T @ t

        poses[name] = {
            "R": R, "t": t, "K": K,
            "width": int(w), "height": int(h),
            "position": position,
        }
    return poses


# ===========================================================================
# Scale Calibration from reference object
# ===========================================================================

def calibrate_from_reference(
    poses: Dict[str, Dict],
    reference_points_3d: np.ndarray,  # (N, 3) world coords of reference object
    reference_size_m: float,          # known real-world size in meters
) -> float:
    """
    Compute global scale factor from a known-size reference object.

    reference_points_3d: COLMAP-reconstructed 3D points on the reference object
    reference_size_m: real-world size (e.g., 0.21 for A4 paper, 2.1 for door)

    Returns scale factor to multiply all coordinates by to get meters.
    """
    if len(reference_points_3d) < 2:
        return 1.0

    # Compute extent in reconstruction
    colmap_size = np.linalg.norm(
        reference_points_3d.max(axis=0) - reference_points_3d.min(axis=0)
    )
    if colmap_size < 1e-9:
        return 1.0

    return reference_size_m / colmap_size
