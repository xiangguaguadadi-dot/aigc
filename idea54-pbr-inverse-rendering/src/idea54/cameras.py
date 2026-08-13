from __future__ import annotations

import numpy as np


def look_at(eye: np.ndarray, target: np.ndarray | None = None) -> np.ndarray:
    eye = np.asarray(eye, dtype=np.float32)
    target = np.zeros(3, dtype=np.float32) if target is None else np.asarray(target, dtype=np.float32)
    forward = target - eye
    forward /= np.linalg.norm(forward)
    up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-5:
        up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    true_up = np.cross(right, forward)
    rotation = np.stack([right, true_up, -forward], axis=0)
    transform = np.eye(4, dtype=np.float32)
    transform[:3, :3] = rotation
    transform[:3, 3] = -rotation @ eye
    return transform


def perspective_intrinsics(width: int, height: int, fov_y_degrees: float = 45.0) -> np.ndarray:
    fy = 0.5 * height / np.tan(np.deg2rad(fov_y_degrees) / 2.0)
    fx = fy
    return np.array([[fx, 0, width / 2], [0, fy, height / 2], [0, 0, 1]], dtype=np.float32)


def projection_from_intrinsics(k, width: int, height: int, near: float, far: float):
    import torch

    projection = torch.zeros((4, 4), dtype=k.dtype, device=k.device)
    projection[0, 0] = 2.0 * k[0, 0] / width
    projection[1, 1] = 2.0 * k[1, 1] / height
    projection[0, 2] = 1.0 - 2.0 * k[0, 2] / width
    projection[1, 2] = 2.0 * k[1, 2] / height - 1.0
    projection[2, 2] = -(far + near) / (far - near)
    projection[2, 3] = -(2.0 * far * near) / (far - near)
    projection[3, 2] = -1.0
    return projection
