"""Record PyBullet interaction frames for deterministic Blender replay."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class TrajectoryRecorder:
    """Capture robot visual-link poses, object poses, and command boundaries."""

    FORMAT_VERSION = 1

    def __init__(
        self,
        run_dir: str | Path,
        simulation_dt: float,
        output_fps: int = 30,
        environment_path: str | Path | None = None,
    ):
        if output_fps <= 0:
            raise ValueError("output_fps must be positive")
        self.run_dir = Path(run_dir).resolve()
        self.simulation_dt = float(simulation_dt)
        self.output_fps = int(output_fps)
        simulation_fps = 1.0 / self.simulation_dt
        self.sample_stride = max(1, round(simulation_fps / self.output_fps))
        self.environment_path = _absolute_optional_path(environment_path)

        self.simulation_step = 0
        self.frames: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []
        self.scene_manifest: dict[str, Any] = {}
        self.active_command = "initial"
        self._active_command_index: int | None = None
        self._visual_shapes: list[dict[str, Any]] = []

    def start(self, scene) -> None:
        """Read static scene metadata and capture the initial pose."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._visual_shapes = self._describe_robot_visuals(scene)
        object_path = _absolute_optional_path(scene.object_path)
        self.scene_manifest = {
            "format_version": self.FORMAT_VERSION,
            "created_at": datetime.now().astimezone().isoformat(),
            "coordinate_system": "right-handed, Z-up, meters, quaternion XYZW",
            "simulation_dt": self.simulation_dt,
            "output_fps": self.output_fps,
            "sample_stride": self.sample_stride,
            "robot": {
                "type": "Franka Panda",
                "base_position": _numbers(scene.robot_base),
                "visual_shapes": self._visual_shapes,
            },
            "object": {
                "source_path": object_path,
                "scale": float(scene.object_scale),
                "initial_position": _numbers(scene.object_home),
                "fallback": "cube" if object_path is None else None,
                "fallback_size": [0.05, 0.05, 0.05],
            },
            "environment": {
                "source_path": self.environment_path,
                "fallback": "procedural_workbench" if self.environment_path is None else None,
                "table_position": [0.5, 0.0, 0.0],
                "table_top_z": 0.626,
            },
        }
        self.capture(scene, force=True)

    def begin_command(self, command: str, scene) -> None:
        """Open a command interval and preserve its exact starting pose."""
        self.active_command = command
        self.capture(scene, force=True)
        self._active_command_index = len(self.commands)
        self.commands.append(
            {
                "index": self._active_command_index,
                "command": command,
                "start_frame": len(self.frames),
                "start_simulation_step": self.simulation_step,
                "status": "running",
            }
        )

    def end_command(self, scene, status: str = "completed") -> None:
        """Close the current command interval and preserve its final pose."""
        self.capture(scene, force=True)
        if self._active_command_index is not None:
            command = self.commands[self._active_command_index]
            command["end_frame"] = len(self.frames)
            command["end_simulation_step"] = self.simulation_step
            command["status"] = status
        self._active_command_index = None

    def on_simulation_step(self, scene) -> None:
        """Observer callback called by CommandScene after each physics step."""
        self.simulation_step += 1
        if self.simulation_step % self.sample_stride == 0:
            self.capture(scene)

    def capture(self, scene, force: bool = False) -> None:
        """Capture one replay frame from the current PyBullet state."""
        if not force and self.frames and self.frames[-1]["simulation_step"] == self.simulation_step:
            return

        p = scene.p
        robot = scene.robot
        object_pos, object_orn = scene.env.get_body_pose(scene.object_id)
        ee_pos, ee_orn = robot.get_end_effector_pose()
        link_poses = {}
        for shape in self._visual_shapes:
            position, orientation = _visual_world_pose(p, robot.body_id, shape)
            link_poses[shape["id"]] = {
                "position": _numbers(position),
                "orientation": _numbers(orientation),
            }

        self.frames.append(
            {
                "frame": len(self.frames) + 1,
                "simulation_step": self.simulation_step,
                "time_seconds": round(self.simulation_step * self.simulation_dt, 6),
                "command": self.active_command,
                "robot_links": link_poses,
                "joint_positions": {
                    name: float(value) for name, value in robot.get_joint_positions().items()
                },
                "end_effector": {
                    "position": _numbers(ee_pos),
                    "orientation": _numbers(ee_orn),
                },
                "gripper_opening": float(robot.get_gripper_opening()),
                "object": {
                    "position": _numbers(object_pos),
                    "orientation": _numbers(object_orn),
                },
                "grasped": bool(scene.grasped),
            }
        )

    def save(self) -> dict[str, Path]:
        """Write all replay artifacts atomically enough for a local demo workflow."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self._active_command_index is not None:
            command = self.commands[self._active_command_index]
            command["end_frame"] = len(self.frames)
            command["end_simulation_step"] = self.simulation_step
            command["status"] = "interrupted"
            self._active_command_index = None

        trajectory = {
            "format_version": self.FORMAT_VERSION,
            "fps": self.output_fps,
            "frame_count": len(self.frames),
            "duration_seconds": round(len(self.frames) / self.output_fps, 3),
            "frames": self.frames,
        }
        paths = {
            "trajectory": self.run_dir / "trajectory.json",
            "commands": self.run_dir / "commands.json",
            "scene_manifest": self.run_dir / "scene_manifest.json",
        }
        _write_json(paths["trajectory"], trajectory)
        _write_json(paths["commands"], {"commands": self.commands})
        _write_json(paths["scene_manifest"], self.scene_manifest)
        return paths

    @staticmethod
    def _describe_robot_visuals(scene) -> list[dict[str, Any]]:
        p = scene.p
        body_id = scene.robot.body_id
        result = []
        for shape_index, data in enumerate(p.getVisualShapeData(body_id)):
            link_index = int(data[1])
            if link_index == -1:
                link_name = "panda_link0"
            else:
                link_name = p.getJointInfo(body_id, link_index)[12].decode("utf-8")
            mesh_path = data[4].decode("utf-8") if isinstance(data[4], bytes) else str(data[4])
            mesh_path = str(Path(mesh_path).resolve()) if mesh_path else None
            result.append(
                {
                    "id": f"visual_{shape_index:02d}_{link_name}",
                    "link_index": link_index,
                    "link_name": link_name,
                    "geometry_type": int(data[2]),
                    "dimensions": _numbers(data[3]),
                    "mesh_path": mesh_path,
                    "local_position": _numbers(data[5]),
                    "local_orientation": _numbers(data[6]),
                    "rgba": _numbers(data[7]),
                }
            )
        return result


def _visual_world_pose(p, body_id: int, shape: dict[str, Any]):
    link_index = shape["link_index"]
    if link_index == -1:
        link_pos, link_orn = p.getBasePositionAndOrientation(body_id)
    else:
        link_state = p.getLinkState(body_id, link_index, computeForwardKinematics=True)
        link_pos, link_orn = link_state[4], link_state[5]
    return p.multiplyTransforms(
        link_pos,
        link_orn,
        shape["local_position"],
        shape["local_orientation"],
    )


def _numbers(values) -> list[float]:
    return [float(value) for value in values]


def _absolute_optional_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    return str(path.resolve())


def _write_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    temporary.replace(path)
