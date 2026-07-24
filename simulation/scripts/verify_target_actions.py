"""Headless acceptance checks for target feasibility and physical target actions."""

from __future__ import annotations

import json

import numpy as np
import pybullet as p

from simulation.env import SimulationEnv
from simulation.robots.panda import PandaRobot
from simulation.scripts.command_robot import CommandScene


def main() -> None:
    scene = CommandScene(
        p=p,
        env=SimulationEnv(gui=False),
        robot_base=np.array([0.0, -0.35, 0.626]),
        object_path=None,
        object_scale=0.05,
        object_mass=0.08,
        object_friction=0.8,
        object_position=np.array([0.5, 0.0, 0.66]),
        step_delay=0.0,
        dt=1 / 240,
    )
    report = None
    try:
        scene.setup(PandaRobot)
        reachable = scene.assess_action("move_to", np.array([0.48, 0.08, 0.88]))
        unreachable = scene.assess_action("move_to", np.array([2.5, 0.0, 1.0]))
        _require(reachable["feasible"], reachable["summary"])
        _require(not unreachable["feasible"], "Unreachable target was accepted")

        push_start, _ = scene.env.get_body_pose(scene.object_id)
        push_target = push_start + np.array([0.12, 0.0, 0.0])
        push_check = scene.assess_action("push_to", push_target)
        _require(push_check["feasible"], push_check["summary"])
        _require(
            "planned_surface_contact_m" in push_check["metrics"],
            "Push feasibility did not resolve a collision-mesh contact point",
        )
        _require(
            push_check["metrics"]["contact_position_error_m"] < 0.055,
            "Push feasibility accepted an inaccurate contact IK pose",
        )
        scene.push_to(push_target)
        first_push_details = dict(scene.last_action_details)
        push_end, _ = scene.env.get_body_pose(scene.object_id)
        push_distance = float(np.linalg.norm(push_end[:2] - push_start[:2]))
        _require(scene.grasp_constraint_id is None, "Push created a grasp constraint")
        _require(push_distance > 0.05, f"Push displacement too small: {push_distance:.3f} m")
        _require(
            scene.last_action_details["metrics"]["peak_contact_force_n"] >= 1.0,
            "Push completed without measured contact force",
        )

        scene.reset_scene()
        second_push_start, _ = scene.env.get_body_pose(scene.object_id)
        second_push_target = second_push_start + np.array([0.0, 0.10, 0.0])
        scene.push_to(second_push_target)
        second_push_end, _ = scene.env.get_body_pose(scene.object_id)
        second_push_distance = float(
            np.linalg.norm(second_push_end[:2] - second_push_start[:2])
        )
        _require(
            second_push_distance > 0.04,
            f"Cross-axis push displacement too small: {second_push_distance:.3f} m",
        )

        scene.reset_scene()
        _require(scene.execute("pick"), scene.last_error)
        _require(scene.execute("lift"), scene.last_error)
        quarter_turn = np.asarray(p.getQuaternionFromEuler([0.0, 0.0, np.pi / 2]))
        rotate_check = scene.assess_action("rotate_to", target_orientation=quarter_turn)
        _require(rotate_check["feasible"], rotate_check["summary"])
        scene.rotate_object_to(quarter_turn)
        _, rotated_orientation = scene.env.get_body_pose(scene.object_id)
        rotation_error = scene._quaternion_angle(rotated_orientation, quarter_turn)
        _require(rotation_error < np.deg2rad(8.0), "Target rotation did not converge")

        place_marker = np.array([0.5, -0.16, scene.table_top_z])
        place_check = scene.assess_action("place_at", place_marker, quarter_turn)
        _require(place_check["feasible"], place_check["summary"])
        scene.place(place_marker, quarter_turn)
        placed_position, placed_orientation = scene.env.get_body_pose(scene.object_id)
        place_error = float(np.linalg.norm(placed_position[:2] - place_marker[:2]))
        placed_rotation_error = scene._quaternion_angle(placed_orientation, quarter_turn)
        _require(place_error < 0.04, f"Placed target error too large: {place_error:.3f} m")
        _require(placed_rotation_error < np.deg2rad(12.0), "Placed orientation was not preserved")

        report = {
            "reachable_check": reachable["feasible"],
            "unreachable_rejected": not unreachable["feasible"],
            "push_displacement_m": push_distance,
            "cross_axis_push_displacement_m": second_push_distance,
            "push_peak_contact_force_n": first_push_details["metrics"]["peak_contact_force_n"],
            "rotation_error_deg": float(np.rad2deg(rotation_error)),
            "place_error_m": place_error,
            "placed_rotation_error_deg": float(np.rad2deg(placed_rotation_error)),
        }
    finally:
        scene.close()
    report["floor_push_displacement_m"] = _verify_floor_push()
    print("TARGET_ACTION_REPORT=" + json.dumps(report, ensure_ascii=False))


def _verify_floor_push() -> float:
    scene = CommandScene(
        p=p,
        env=SimulationEnv(gui=False),
        robot_base=np.array([0.0, -0.35, 0.0]),
        object_path=None,
        object_scale=0.05,
        object_mass=0.08,
        object_friction=0.5,
        scene_profile="floor",
        object_position=np.array([0.5, 0.0, 0.2]),
        step_delay=0.0,
        dt=1 / 240,
    )
    try:
        scene.setup(PandaRobot)
        start, _ = scene.env.get_body_pose(scene.object_id)
        target = start + np.array([0.10, 0.0, 0.0])
        _require(scene.assess_action("push_to", target)["feasible"], "Floor push was rejected")
        scene.push_to(target)
        end, _ = scene.env.get_body_pose(scene.object_id)
        distance = float(np.linalg.norm(end[:2] - start[:2]))
        _require(distance > 0.05, f"Floor push displacement too small: {distance:.3f} m")
        return distance
    finally:
        scene.close()


def _require(condition, message) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
