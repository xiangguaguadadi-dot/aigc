"""Headless acceptance checks for torque control and contact-gated grasping."""

from __future__ import annotations

import json

import numpy as np
import pybullet as p

from simulation.env import SimulationEnv
from simulation.robots.panda import PandaRobot
from simulation.scripts.command_robot import CommandScene, GraspFailure


def main() -> None:
    scene = CommandScene(
        p=p,
        env=SimulationEnv(gui=False),
        robot_base=np.array([0.0, -0.35, 0.626]),
        object_path=None,
        object_scale=0.05,
        object_position=np.array([0.5, 0.0, 0.66]),
        step_delay=0.0,
        dt=1 / 240,
    )
    peak_torques = np.zeros(7, dtype=float)

    def observe(current_scene: CommandScene) -> None:
        nonlocal peak_torques
        commanded = current_scene.robot.last_arm_torques
        if not np.all(np.isfinite(commanded)):
            raise AssertionError("Non-finite arm torque was reported")
        peak_torques = np.maximum(peak_torques, np.abs(commanded))

    try:
        scene.setup(PandaRobot)
        scene.frame_observer = observe

        initial_object, _ = scene.env.get_body_pose(scene.object_id)
        _require(scene.execute("pick"), scene.last_error)
        contacts = scene.last_grasp_contact_summary
        _require(contacts and contacts["valid"], "Pick completed without valid force closure")
        _require(scene.grasp_constraint_id is not None, "Contact stabilizer was not created")
        forces = [float(finger["force"]) for finger in contacts["fingers"]]
        _require(all(force >= scene.minimum_contact_force for force in forces), "Finger force too low")
        normal_dot = float(
            np.dot(contacts["fingers"][0]["normal"], contacts["fingers"][1]["normal"])
        )
        _require(normal_dot < -0.5, "Finger contact normals are not opposing")

        _require(scene.execute("lift"), scene.last_error)
        lifted_object, _ = scene.env.get_body_pose(scene.object_id)
        _require(lifted_object[2] - initial_object[2] > 0.12, "Object did not physically lift")

        _require(scene.execute("release"), scene.last_error)
        released_object, _ = scene.env.get_body_pose(scene.object_id)
        released_lower, _ = p.getAABB(scene.object_id)
        _require(not scene.grasped, "Release left the scene in grasped state")
        _require(scene.grasp_constraint_id is None, "Release left a grasp constraint active")
        _require(abs(released_lower[2] - scene.table_top_z) < 0.004, "Released object did not settle on table")

        scene.reset_scene()
        scene.open_gripper()
        scene._move_grasp_to(np.array([0.5, 0.15, initial_object[2]], dtype=float))
        failed_without_contact = False
        try:
            scene.close_gripper()
        except GraspFailure:
            failed_without_contact = True
        _require(failed_without_contact, "Off-center grasp unexpectedly succeeded")
        _require(not scene.grasped, "Failed grasp marked the object as grasped")
        _require(scene.grasp_constraint_id is None, "Failed grasp created a constraint")

        stop_counter = 0

        def stop_during_motion(current_scene: CommandScene) -> None:
            nonlocal stop_counter
            observe(current_scene)
            stop_counter += 1
            if stop_counter == 8:
                current_scene.request_stop()

        scene.frame_observer = stop_during_motion
        stopped = scene.execute("home")
        _require(not stopped and scene.last_command_status == "cancelled", "Torque trajectory did not stop")
        scene.frame_observer = observe
        scene.clear_stop()

        _require(
            np.all(peak_torques <= scene.robot.arm_torque_limits + 1e-6),
            f"Torque limit exceeded: {peak_torques.tolist()}",
        )
        report = {
            "control_mode": "inverse_dynamics_torque",
            "pick_contact_valid": True,
            "finger_forces_n": forces,
            "contact_normal_dot": normal_dot,
            "lift_delta_m": float(lifted_object[2] - initial_object[2]),
            "released_object_z_m": float(released_object[2]),
            "failed_grasp_rejected": failed_without_contact,
            "stop_status": scene.last_command_status,
            "peak_joint_torques_nm": peak_torques.tolist(),
            "torque_limits_nm": scene.robot.arm_torque_limits.tolist(),
        }
        print("PHYSICAL_INTERACTION_REPORT=" + json.dumps(report, ensure_ascii=False))
    finally:
        scene.close()


def _require(condition, message) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
