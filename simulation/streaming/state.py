"""Serialize a live PyBullet scene into Blender-friendly world transforms."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from simulation.streaming.protocol import PROTOCOL_VERSION


def describe_scene(scene) -> dict[str, Any]:
    objects = []
    for object_id, item in scene.scene_objects.items():
        actual_mass = float(scene.p.getDynamicsInfo(item["body_id"], -1)[0])
        objects.append(
            {
                "id": object_id,
                "label": item.get("label", object_id),
                "source_path": _absolute_optional_path(item.get("source_path")),
                "scale": float(item.get("scale", 1.0)),
                "mass": actual_mass,
                "estimated_mass": float(item.get("mass_kg", actual_mass)),
                "friction": float(item.get("friction", 0.5)),
                "dynamic": bool(item.get("dynamic", True)),
                "initial_position": _numbers(item["home_position"]),
                "initial_orientation": _numbers(item["home_orientation"]),
                "properties": item.get("properties", {}),
                "fallback": "cube" if item.get("source_path") is None else None,
                "fallback_size": [0.05, 0.05, 0.05],
            }
        )
    active = next(item for item in objects if item["id"] == scene.active_object_id)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "coordinate_system": "right-handed, Z-up, meters, quaternion XYZW",
        "robot": {
            "type": "Franka Panda",
            "base_position": _numbers(scene.robot_base),
            "visual_shapes": describe_robot_visuals(scene),
        },
        "active_object_id": scene.active_object_id,
        "objects": objects,
        "object": active,
        "table": {
            "enabled": scene.env.body_ids.get("table") is not None,
            "position": [0.5, 0.0, 0.0],
            "top_z": 0.626,
        },
        "scene_profile": scene.scene_profile,
    }


def describe_robot_visuals(scene) -> list[dict[str, Any]]:
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


def capture_state(
    scene,
    visual_shapes: list[dict[str, Any]],
    sequence: int,
    active_command: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = scene.p
    robot = scene.robot
    object_states = {}
    for object_id, item in scene.scene_objects.items():
        position, orientation = scene.env.get_body_pose(item["body_id"])
        object_states[object_id] = {
            "position": _numbers(position),
            "orientation": _numbers(orientation),
        }
    active_object = object_states[scene.active_object_id]
    ee_pos, ee_orn = robot.get_end_effector_pose()
    robot_links = {}
    for shape in visual_shapes:
        position, orientation = visual_world_pose(p, robot.body_id, shape)
        robot_links[shape["id"]] = {
            "position": _numbers(position),
            "orientation": _numbers(orientation),
        }

    return {
        "type": "state",
        "protocol_version": PROTOCOL_VERSION,
        "sequence": int(sequence),
        "server_time": time.time(),
        "command": active_command,
        "robot_links": robot_links,
        "joint_positions": {
            name: float(value) for name, value in robot.get_joint_positions().items()
        },
        "joint_torques": {
            name: float(robot.last_arm_torques[index])
            for index, name in enumerate(robot.arm_joint_names)
        },
        "end_effector": {
            "position": _numbers(ee_pos),
            "orientation": _numbers(ee_orn),
        },
        "gripper_opening": float(robot.get_gripper_opening()),
        "active_object_id": scene.active_object_id,
        "objects": object_states,
        "object": active_object,
        "grasped": bool(scene.grasped),
        "control_mode": "inverse_dynamics_torque",
        "grasp_constraint_active": scene.grasp_constraint_id is not None,
        "grasp_contacts": scene.last_grasp_contact_summary,
    }


def visual_world_pose(p, body_id: int, shape: dict[str, Any]):
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
    return str(Path(value).expanduser().resolve())
