"""Interactive demo: Franka Panda pick-and-place.

Usage:
    python -m simulation.scripts.demo_pick
    python -m simulation.scripts.demo_pick --object outputs/xxx/export/reconstructed.glb
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Robot pick-and-place demo")
    parser.add_argument("--object", "-o", default=None, help="Path to GLB/URDF object")
    parser.add_argument("--object-scale", type=float, default=0.05, help="Scale for GLB/URDF object meshes")
    parser.add_argument(
        "--robot-base",
        default="0,-0.35,0.626",
        help="Robot base position as x,y,z. Default mounts Panda on the tabletop.",
    )
    parser.add_argument("--no-gui", action="store_true", help="Headless mode")
    parser.add_argument("--auto", action="store_true", help="Play all demo steps automatically in GUI")
    parser.add_argument("--step-delay", type=float, default=0.015, help="Delay between visual frames in GUI")
    parser.add_argument("--dt", type=float, default=1 / 240, help="Physics timestep")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(project_root))

    import pybullet as p
    from simulation.env import SimulationEnv
    from simulation.robots.panda import PandaRobot

    robot_base = _parse_xyz(args.robot_base)

    print("=" * 60)
    print("Part 3: Robot Simulation Demo")
    print("=" * 60)
    print("Controls: drag slider to set step | Q to quit")

    print("\n[1/5] Creating simulation environment...")
    env = SimulationEnv(gui=not args.no_gui)
    p.setPhysicsEngineParameter(deterministicOverlappingPairs=1)
    p.setTimeStep(args.dt)
    np.random.seed(args.seed)

    p.resetDebugVisualizerCamera(
        cameraDistance=1.8,
        cameraYaw=25,
        cameraPitch=-40,
        cameraTargetPosition=[0.25, -0.15, 0.75],
    )

    print("[2/5] Loading table...")
    env.load_ground()
    env.load_table(position=[0.5, 0, 0])

    print("[3/5] Loading object...")
    obj_pos = np.array([0.5, 0, 0.66], dtype=float)
    if args.object:
        obj_path = Path(args.object)
        if obj_path.exists():
            obj_id = env.load_object(obj_path, obj_pos, scale=args.object_scale)
        else:
            print(f"  WARNING: {obj_path} not found, using demo box")
            obj_id = _load_demo_box(p, obj_pos)
    else:
        print("  Using red demo box (--object to use your GLB)")
        obj_id = _load_demo_box(p, obj_pos)

    for _ in range(120):
        env.step()
    obj_pos, _ = env.get_body_pose(obj_id)

    print("[4/5] Loading Franka Panda robot...")
    robot = PandaRobot(base_position=robot_base.tolist())
    robot.load()
    robot.reset_home()
    _disable_robot_scene_collisions(p, robot.body_id, obj_id, env.body_ids.get("table"))

    above = obj_pos + np.array([0, 0, 0.12])
    target_steps = 80
    frame_delay = 0.0 if args.no_gui else args.step_delay
    grasped = False
    grasp_offset = np.zeros(3, dtype=float)

    step_names = [
        "Move above object",
        "Open gripper",
        "Approach object",
        "Close gripper",
        "Lift object",
    ]

    def step_move_above():
        _move_robot_visual(p, robot, above, steps=target_steps, delay=frame_delay)

    def step_open_gripper():
        nonlocal grasped
        robot.open_gripper()
        grasped = False
        for _ in range(30):
            env.step()
            if frame_delay > 0:
                time.sleep(frame_delay)

    def step_approach():
        _move_robot_visual(
            p,
            robot,
            obj_pos + np.array([0, 0, 0.025]),
            steps=target_steps,
            delay=frame_delay,
        )

    def step_close_gripper():
        nonlocal grasped, grasp_offset
        robot.close_gripper()
        ee_pos, _ = robot.get_end_effector_pose()
        current_obj_pos, _ = env.get_body_pose(obj_id)
        grasp_offset = current_obj_pos - ee_pos
        grasped = True
        for _ in range(20):
            _sync_grasped_object(p, robot, obj_id, grasp_offset)
            env.step()
            if frame_delay > 0:
                time.sleep(frame_delay)

    def step_lift():
        _move_robot_visual(
            p,
            robot,
            above + np.array([0, 0, 0.12]),
            steps=target_steps,
            delay=frame_delay,
            follow_object=obj_id if grasped else None,
            grasp_offset=grasp_offset,
        )

    actions = [step_move_above, step_open_gripper, step_approach, step_close_gripper, step_lift]

    if args.no_gui or args.auto:
        for i, action in enumerate(actions):
            print(f"\n[{i + 1}/5] {step_names[i]}...")
            action()
        print("\nPick-and-place complete.")
        if args.auto and not args.no_gui:
            print("Press Q in the PyBullet window to quit.")
            while True:
                for key_code, state in p.getKeyboardEvents().items():
                    if state & p.KEY_WAS_TRIGGERED:
                        char = chr(key_code) if key_code < 256 else ""
                        if char.lower() == "q":
                            env.disconnect()
                            return
                if grasped:
                    _sync_grasped_object(p, robot, obj_id, grasp_offset)
                env.step()
                time.sleep(0.01)
        env.disconnect()
        return

    step_slider = p.addUserDebugParameter("Step (drag to advance)", 0, 5, 0)
    status_text = p.addUserDebugText(
        "Step 0/5: Ready - drag slider to 1 to begin",
        textPosition=[0, 0, 0.9],
        textColorRGB=[1, 1, 1],
        textSize=1.2,
        lifeTime=0,
    )

    print("\nDrag the slider to advance steps:")
    print("  0 = start | 1 = move above | 2 = open gripper")
    print("  3 = approach | 4 = close | 5 = lift")

    executed_steps = set()
    try:
        while True:
            slider_val = int(round(p.readUserDebugParameter(step_slider)))

            if slider_val > 0:
                for step_number in range(1, min(slider_val, len(actions)) + 1):
                    if step_number in executed_steps:
                        continue
                    step_idx = step_number - 1
                    name = step_names[step_idx]
                    print(f"\n--- Step {slider_val}/5: {name} ---")
                    p.addUserDebugText(
                        f"Step {step_number}/5: {name}...",
                        textPosition=[0, 0, 0.9],
                        textColorRGB=[0, 1, 0],
                        textSize=1.2,
                        lifeTime=0,
                        replaceItemUniqueId=status_text,
                    )
                    actions[step_idx]()
                    executed_steps.add(step_number)
                    print("  Done")
                    p.addUserDebugText(
                        f"Step {step_number}/5: Done - drag to next step",
                        textPosition=[0, 0, 0.9],
                        textColorRGB=[1, 1, 0],
                        textSize=1.2,
                        lifeTime=0,
                        replaceItemUniqueId=status_text,
                    )
            elif slider_val == 0 and executed_steps:
                print("\nResetting robot...")
                executed_steps.clear()
                p.removeBody(robot.body_id)
                robot = PandaRobot(base_position=robot_base.tolist())
                robot.load()
                robot.reset_home()
                _disable_robot_scene_collisions(p, robot.body_id, obj_id, env.body_ids.get("table"))
                p.addUserDebugText(
                    "Reset - drag slider to 1 to begin again",
                    textPosition=[0, 0, 0.9],
                    textColorRGB=[1, 1, 1],
                    textSize=1.2,
                    lifeTime=0,
                    replaceItemUniqueId=status_text,
                )

            for key_code, state in p.getKeyboardEvents().items():
                if state & p.KEY_WAS_TRIGGERED:
                    char = chr(key_code) if key_code < 256 else ""
                    if char.lower() == "q":
                        env.disconnect()
                        print("\nQuit.")
                        return

            if grasped:
                _sync_grasped_object(p, robot, obj_id, grasp_offset)
            env.step()
            time.sleep(0.005)

    except KeyboardInterrupt:
        env.disconnect()


def _load_demo_box(p, position: np.ndarray) -> int:
    half_extents = [0.025, 0.025, 0.025]
    collision = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents)
    visual = p.createVisualShape(
        p.GEOM_BOX,
        halfExtents=half_extents,
        rgbaColor=[0.9, 0.12, 0.1, 1.0],
    )
    obj_id = p.createMultiBody(
        baseMass=0.08,
        baseCollisionShapeIndex=collision,
        baseVisualShapeIndex=visual,
        basePosition=tuple(position),
    )
    p.changeDynamics(obj_id, -1, lateralFriction=0.8, spinningFriction=0.02, rollingFriction=0.02)
    return obj_id


def _parse_xyz(value: str) -> np.ndarray:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError("--robot-base must be formatted as x,y,z")
    return np.array(parts, dtype=float)


def _disable_robot_scene_collisions(p, robot_id: int, object_id: int, table_id: int | None):
    for link_idx in range(-1, p.getNumJoints(robot_id)):
        p.setCollisionFilterPair(robot_id, object_id, link_idx, -1, 0)
        if table_id is not None:
            p.setCollisionFilterPair(robot_id, table_id, link_idx, -1, 0)


def _move_robot_visual(
    p,
    robot: "PandaRobot",
    target_pos: np.ndarray,
    steps: int,
    delay: float,
    follow_object: int | None = None,
    grasp_offset: np.ndarray | None = None,
):
    joint_targets = robot.inverse_kinematics(target_pos)
    start = robot.get_joint_positions()
    for step in range(1, steps + 1):
        alpha = step / max(1, steps)
        for name in robot.arm_joint_names:
            if name not in joint_targets:
                continue
            value = (1.0 - alpha) * start.get(name, 0.0) + alpha * joint_targets[name]
            p.resetJointState(robot.body_id, robot._joint_indices[name], value)
        if follow_object is not None and grasp_offset is not None:
            _sync_grasped_object(p, robot, follow_object, grasp_offset)
        p.stepSimulation()
        if delay > 0:
            time.sleep(delay)
    robot.set_joint_positions(joint_targets)


def _sync_grasped_object(p, robot: "PandaRobot", object_id: int, grasp_offset: np.ndarray):
    ee_pos, ee_orn = robot.get_end_effector_pose()
    p.resetBasePositionAndOrientation(object_id, ee_pos + grasp_offset, ee_orn)


if __name__ == "__main__":
    main()
