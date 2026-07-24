"""Geometry-driven 6D antipodal grasp planning with deterministic safety filters."""

from __future__ import annotations

from pathlib import Path

import numpy as np


class AntipodalGraspPlanner:
    """Generate and rank parallel-jaw grasps for the scene's Active Object."""

    def __init__(self, scene, sample_count: int = 900, max_valid_candidates: int = 12):
        self.scene = scene
        self.sample_count = int(sample_count)
        self.max_valid_candidates = int(max_valid_candidates)
        self._surface_cache = {}

    def plan(self) -> dict:
        geometric = self._mesh_candidates()
        source = "mesh_antipodal"
        if not geometric:
            geometric = self._aabb_candidates()
            source = "aabb_fallback"

        valid = []
        evaluated = 0
        for candidate in sorted(geometric, key=lambda item: item["geometric_score"], reverse=True)[:120]:
            evaluated += 1
            grasp_check = self.scene._pose_reachability(
                candidate["position"],
                candidate["orientation"],
                position_tolerance=0.045,
                orientation_tolerance_deg=28.0,
            )
            if not grasp_check["reachable"]:
                continue
            pregrasp_check = self.scene._pose_reachability(
                candidate["pregrasp_position"],
                candidate["orientation"],
                position_tolerance=0.045,
                orientation_tolerance_deg=28.0,
            )
            if not pregrasp_check["reachable"]:
                continue
            joint_targets = self.scene.robot.inverse_kinematics(
                candidate["pregrasp_position"],
                candidate["orientation"],
                link_index=self.scene.robot.grasp_link_index,
            )
            if not self.scene._joint_path_collision_free(joint_targets):
                continue
            candidate = dict(candidate)
            candidate["position_error_m"] = grasp_check["position_error_m"]
            candidate["orientation_error_deg"] = grasp_check["orientation_error_deg"]
            candidate["score"] = float(
                candidate["geometric_score"]
                - min(0.20, 2.0 * grasp_check["position_error_m"])
                - min(0.10, grasp_check["orientation_error_deg"] / 280.0)
            )
            valid.append(candidate)
            if len(valid) >= self.max_valid_candidates:
                break

        valid.sort(key=lambda item: item["score"], reverse=True)
        return {
            "source": source,
            "sample_count": self.sample_count if source == "mesh_antipodal" else 0,
            "geometric_candidate_count": len(geometric),
            "evaluated_candidate_count": evaluated,
            "valid_candidate_count": len(valid),
            "candidates": valid,
        }

    def _mesh_candidates(self) -> list[dict]:
        surface = self._local_surface()
        if surface is None:
            return []
        local_points, local_normals = surface
        object_position, object_orientation = self.scene.env.get_body_pose(self.scene.object_id)
        rotation = _rotation_matrix(object_orientation)
        points = local_points @ rotation.T + object_position
        normals = local_normals @ rotation.T

        try:
            from scipy.spatial import cKDTree
        except ImportError:
            return []
        tree = cKDTree(points)
        maximum_width = self.scene.gripper_max_object_width - 0.004
        object_center = np.mean(np.asarray(self.scene.p.getAABB(self.scene.object_id)), axis=0)
        object_extent = np.ptp(points, axis=0)
        scale = max(0.03, float(np.linalg.norm(object_extent)))
        candidates = []
        seen = set()

        for first in range(len(points)):
            neighbor_indices = np.asarray(tree.query_ball_point(points[first], maximum_width), dtype=int)
            neighbor_indices = neighbor_indices[neighbor_indices > first]
            if not len(neighbor_indices):
                continue
            vectors = points[neighbor_indices] - points[first]
            widths = np.linalg.norm(vectors, axis=1)
            valid_width = widths >= 0.012
            neighbor_indices = neighbor_indices[valid_width]
            vectors = vectors[valid_width]
            widths = widths[valid_width]
            if not len(neighbor_indices):
                continue
            axes = vectors / widths[:, None]
            opposition = -(normals[neighbor_indices] @ normals[first])
            alignment = 0.5 * (
                np.abs(axes @ normals[first])
                + np.abs(np.sum(normals[neighbor_indices] * axes, axis=1))
            )
            quality = 0.5 * opposition + 0.5 * alignment
            valid = np.flatnonzero((opposition >= 0.55) & (alignment >= 0.62))
            if len(valid) > 10:
                valid = valid[np.argsort(quality[valid])[-10:]]
            for candidate_index in valid:
                second = int(neighbor_indices[candidate_index])
                width = float(widths[candidate_index])
                axis = axes[candidate_index]
                normal_opposition = float(opposition[candidate_index])
                axis_alignment = float(alignment[candidate_index])
                midpoint = (points[first] + points[second]) / 2.0
                key = tuple(np.round(np.r_[midpoint / 0.012, np.abs(axis) / 0.15]).astype(int))
                if key in seen:
                    continue
                seen.add(key)
                force_score = float(np.clip(0.5 * normal_opposition + 0.5 * axis_alignment, 0.0, 1.0))
                center_score = float(np.exp(-np.linalg.norm(midpoint - object_center) / (0.30 * scale)))
                width_score = float(
                    np.clip(
                        (self.scene.gripper_max_object_width - width)
                        / max(0.02, self.scene.gripper_max_object_width - 0.012),
                        0.0,
                        1.0,
                    )
                )
                for approach, top_score in _approach_directions(axis):
                    pregrasp = midpoint - approach * 0.12
                    if pregrasp[2] < self.scene.minimum_end_effector_z:
                        continue
                    orientation = _grasp_orientation(axis, approach)
                    geometric_score = (
                        0.45 * force_score
                        + 0.30 * center_score
                        + 0.15 * top_score
                        + 0.10 * width_score
                    )
                    candidates.append(
                        {
                            "position": midpoint.copy(),
                            "orientation": orientation,
                            "pregrasp_position": pregrasp,
                            "opening_m": width,
                            "contact_points": [points[first].copy(), points[second].copy()],
                            "contact_normals": [normals[first].copy(), normals[second].copy()],
                            "approach_direction": approach,
                            "closing_axis": axis,
                            "force_closure_score": force_score,
                            "center_score": center_score,
                            "geometric_score": float(geometric_score),
                        }
                    )
        return candidates

    def _aabb_candidates(self) -> list[dict]:
        lower, upper = (
            np.asarray(value, dtype=float) for value in self.scene.p.getAABB(self.scene.object_id)
        )
        center = (lower + upper) / 2.0
        dimensions = upper - lower
        candidates = []
        for axis_index in (0, 1):
            width = float(dimensions[axis_index])
            if width > self.scene.gripper_max_object_width - 0.002:
                continue
            closing = np.zeros(3, dtype=float)
            closing[axis_index] = 1.0
            approach = np.array([0.0, 0.0, -1.0], dtype=float)
            orientation = _grasp_orientation(closing, approach)
            contact_offset = closing * width / 2.0
            candidates.append(
                {
                    "position": center.copy(),
                    "orientation": orientation,
                    "pregrasp_position": center - approach * 0.18,
                    "opening_m": width,
                    "contact_points": [center - contact_offset, center + contact_offset],
                    "contact_normals": [-closing, closing],
                    "approach_direction": approach,
                    "closing_axis": closing,
                    "force_closure_score": 0.65,
                    "center_score": 1.0,
                    "geometric_score": 0.72,
                }
            )
        return candidates

    def _local_surface(self):
        path = self.scene.object_path
        if path is None or path.suffix.lower() not in {".glb", ".gltf", ".obj", ".ply"}:
            return None
        path = Path(path).resolve()
        if not path.exists():
            return None
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, float(self.scene.object_scale))
        if key in self._surface_cache:
            return self._surface_cache[key]

        try:
            import trimesh

            loaded = trimesh.load(str(path), force="scene")
            mesh = loaded.to_geometry() if isinstance(loaded, trimesh.Scene) else loaded
            points, face_indices = trimesh.sample.sample_surface(
                mesh,
                self.sample_count,
                seed=17,
            )
            normals = np.asarray(mesh.face_normals)[face_indices]
        except Exception:
            return None

        if path.suffix.lower() in {".glb", ".gltf"}:
            transform = np.array(
                [
                    [1.0, 0.0, 0.0],
                    [0.0, 0.0, -1.0],
                    [0.0, 1.0, 0.0],
                ]
            )
            points = points @ transform.T
            normals = normals @ transform.T
        points = np.asarray(points, dtype=float) * float(self.scene.object_scale)
        normals = np.asarray(normals, dtype=float)
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
        self._surface_cache[key] = (points, normals)
        return points, normals


def serialize_grasp(candidate: dict) -> dict:
    result = {}
    for key, value in candidate.items():
        if isinstance(value, np.ndarray):
            result[key] = value.tolist()
        elif isinstance(value, list) and value and isinstance(value[0], np.ndarray):
            result[key] = [item.tolist() for item in value]
        elif isinstance(value, (np.floating, np.integer)):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def _approach_directions(closing_axis: np.ndarray):
    closing_axis = closing_axis / max(float(np.linalg.norm(closing_axis)), 1e-9)
    downward = np.array([0.0, 0.0, -1.0], dtype=float)
    base = downward - closing_axis * float(np.dot(downward, closing_axis))
    if np.linalg.norm(base) < 1e-5:
        base = np.array([1.0, 0.0, 0.0], dtype=float)
        base -= closing_axis * float(np.dot(base, closing_axis))
    base /= np.linalg.norm(base)
    tangent = np.cross(closing_axis, base)
    tangent /= max(float(np.linalg.norm(tangent)), 1e-9)
    for angle in (0.0, np.pi / 4, -np.pi / 4, np.pi / 2, -np.pi / 2):
        approach = np.cos(angle) * base + np.sin(angle) * tangent
        approach /= max(float(np.linalg.norm(approach)), 1e-9)
        top_score = float(np.clip(-approach[2], 0.0, 1.0))
        yield approach, top_score


def _grasp_orientation(closing_axis: np.ndarray, approach_direction: np.ndarray) -> np.ndarray:
    local_y = closing_axis / max(float(np.linalg.norm(closing_axis)), 1e-9)
    local_z = approach_direction - local_y * float(np.dot(approach_direction, local_y))
    local_z /= max(float(np.linalg.norm(local_z)), 1e-9)
    local_x = np.cross(local_y, local_z)
    local_x /= max(float(np.linalg.norm(local_x)), 1e-9)
    rotation = np.column_stack((local_x, local_y, local_z))
    from scipy.spatial.transform import Rotation

    return Rotation.from_matrix(rotation).as_quat()


def _rotation_matrix(quaternion: np.ndarray) -> np.ndarray:
    from scipy.spatial.transform import Rotation

    return Rotation.from_quat(np.asarray(quaternion, dtype=float)).as_matrix()
