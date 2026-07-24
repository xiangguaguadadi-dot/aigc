"""Command-driven Franka Panda interaction demo.

Usage:
    python -m simulation.scripts.command_robot
    python -m simulation.scripts.command_robot --commands "抓取; 抬起; 放到右边"
    python -m simulation.scripts.command_robot --object outputs/xxx/export/reconstructed.glb
"""

import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np

from simulation.grasping.planner import AntipodalGraspPlanner, serialize_grasp
from simulation.scene_manifest import load_scene_manifest


class CommandCancelled(RuntimeError):
    """Raised inside a motion loop when a live stop request arrives."""


class MotionSafetyError(RuntimeError):
    """Raised when a requested joint path would penetrate the tabletop."""


class GraspFailure(RuntimeError):
    """Raised when the two fingers do not establish a valid force closure."""


class ActionFeasibilityError(RuntimeError):
    """Raised when an action cannot be executed under current physical constraints."""


def main():
    parser = argparse.ArgumentParser(description="Command-driven robot control")
    parser.add_argument("--object", "-o", default=None, help="Path to GLB/URDF object")
    parser.add_argument("--scene-manifest", default=None, help="Prepared multi-object scene manifest")
    parser.add_argument("--object-scale", type=float, default=0.05, help="Scale for GLB/URDF object meshes")
    parser.add_argument("--object-mass", type=float, default=0.5, help="Object mass in kilograms")
    parser.add_argument("--object-friction", type=float, default=0.9)
    parser.add_argument("--object-position", default="0.5,0,0.66", help="Initial object base position as x,y,z")
    parser.add_argument("--scene-profile", choices=["tabletop", "floor"], default="tabletop")
    parser.add_argument(
        "--robot-base",
        default=None,
        help="Robot base position as x,y,z. Default mounts Panda on the tabletop.",
    )
    parser.add_argument("--commands", default=None, help="Semicolon-separated commands to run, then exit")
    parser.add_argument("--no-gui", action="store_true", help="Run headless")
    parser.add_argument("--step-delay", type=float, default=0.015, help="Delay between visual frames in GUI")
    parser.add_argument("--dt", type=float, default=1 / 240, help="Physics timestep")
    args = parser.parse_args()
    robot_base = args.robot_base or (
        "0,-0.35,0.626" if args.scene_profile == "tabletop" else "0,-0.35,0"
    )
    if args.object_scale <= 0 or args.object_mass <= 0 or args.object_friction < 0:
        parser.error("object-scale and object-mass must be positive; friction must be non-negative")

    project_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(project_root))

    import pybullet as p
    from simulation.env import SimulationEnv
    from simulation.robots.panda import PandaRobot

    scene = CommandScene(
        p=p,
        env=SimulationEnv(gui=not args.no_gui),
        robot_base=_parse_xyz(robot_base),
        object_path=Path(args.object) if args.object else None,
        object_scale=args.object_scale,
        object_mass=args.object_mass,
        object_friction=args.object_friction,
        scene_profile=args.scene_profile,
        scene_manifest_path=Path(args.scene_manifest) if args.scene_manifest else None,
        step_delay=0.0 if args.no_gui else args.step_delay,
        dt=args.dt,
        object_position=_parse_xyz(args.object_position),
    )
    scene.setup(PandaRobot)

    if args.commands:
        try:
            for command in _split_commands(args.commands):
                if not scene.execute(command):
                    raise SystemExit(1)
        finally:
            scene.close()
        return

    print("\n输入指令控制机械臂。输入 help 查看命令，输入 quit 退出。")
    while True:
        try:
            command = input("robot> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            scene.close()
            return
        if not command:
            scene.idle(20)
            continue
        if command.lower() in {"quit", "exit", "q", "退出"}:
            scene.close()
            return
        scene.execute(command)


class CommandScene:
    """Small command layer over the PyBullet Panda scene."""

    def __init__(
        self,
        p,
        env,
        robot_base: np.ndarray,
        object_path: Path | None,
        object_scale: float,
        step_delay: float,
        dt: float,
        object_position: np.ndarray | None = None,
        object_mass: float = 0.5,
        object_friction: float = 0.9,
        scene_profile: str = "tabletop",
        scene_manifest_path: Path | None = None,
    ):
        self.p = p
        self.env = env
        self.robot_base = robot_base
        self.object_path = object_path
        self.object_scale = object_scale
        self.object_mass = float(object_mass)
        self.object_friction = float(object_friction)
        self.scene_profile = scene_profile
        self.scene_manifest_path = scene_manifest_path
        self.prepared_manifest = None
        self.scene_objects: dict[str, dict] = {}
        self.active_object_id: str | None = None
        self.object_properties: dict = {}
        self.step_delay = step_delay
        self.dt = dt
        self.robot = None
        self.object_id = None
        self.object_home = np.asarray(
            object_position if object_position is not None else [0.5, 0.0, 0.66],
            dtype=float,
        )
        self.object_pos = self.object_home.copy()
        self.grasped = False
        self.grasp_constraint_id = None
        self.last_grasp_contact_summary = None
        self.object_home_orientation = np.array([0, 0, 0, 1], dtype=float)
        self.object_support_offset = 0.025
        self.table_top_z = 0.626
        self.minimum_end_effector_z = self.table_top_z + 0.15 if scene_profile == "tabletop" else 0.12
        self.table_collision_margin = 0.001
        self.above_offset = 0.18
        self.grasp_force = 15.0
        self.gripper_max_object_width = 0.078
        self.minimum_contact_force = 1.0
        self.grasp_constraint_force = 35.0
        self.arm_kp = np.array([120.0, 120.0, 100.0, 100.0, 80.0, 60.0, 40.0])
        self.arm_kd = 2.0 * np.sqrt(self.arm_kp)
        self.arm_hold_target = None
        self.top_down_orientation = None
        self.target_steps = 80
        self.frame_observer = None
        self.stop_event = threading.Event()
        self.last_command_status = "idle"
        self.last_error = None
        self.last_action_details = None
        self.max_payload_mass = 3.0
        self.max_safe_push_force = 35.0
        self.grasp_planner = AntipodalGraspPlanner(self)
        self.last_grasp_plan = None

    def setup(self, robot_cls):
        p = self.p
        p.setPhysicsEngineParameter(
            deterministicOverlappingPairs=1,
            numSolverIterations=150,
            numSubSteps=4,
            enableConeFriction=1,
        )
        p.setTimeStep(self.dt)
        p.resetDebugVisualizerCamera(
            cameraDistance=1.8,
            cameraYaw=25,
            cameraPitch=-40,
            cameraTargetPosition=[0.25, -0.15, 0.75],
        )

        self.env.load_ground()
        if self.scene_profile == "tabletop":
            self.env.load_table(position=[0.5, 0, 0])
        self._load_scene_objects()
        self.idle(120)
        for item in self.scene_objects.values():
            position, orientation = self.env.get_body_pose(item["body_id"])
            lower, _ = p.getAABB(item["body_id"])
            item["home_position"] = position.copy()
            item["home_orientation"] = orientation.copy()
            item["support_offset"] = max(0.0, float(position[2] - lower[2]))
        self._activate_object(self.active_object_id, initial=True)

        self.robot = robot_cls(base_position=self.robot_base.tolist())
        self.robot.load()
        self.robot.reset_home()
        self._configure_scene_collisions()
        self.robot.enable_torque_control()
        self.arm_hold_target, _ = self.robot.get_arm_state()
        self.top_down_orientation = np.asarray(p.getQuaternionFromEuler([np.pi, 0.0, 0.0]))
        print("场景已就绪。")

    def execute(self, command: str, clear_stop: bool = True):
        text = command.strip()
        normalized = text.lower()
        if not text:
            self.last_command_status = "failed"
            self.last_error = "Command is empty"
            return False

        if clear_stop:
            self.clear_stop()
        self.last_command_status = "running"
        self.last_error = None

        try:
            if _is_pick_and_place_command(normalized):
                self.pick()
                self.lift()
                self.place(_parse_place_target(normalized, self.object_home))
            elif normalized in {"help", "帮助", "?"}:
                self.print_help()
            elif normalized in {"home", "reset", "复位", "机械臂复位", "回到初始位置", "回家"}:
                self.home()
            elif normalized in {"open", "open gripper", "打开", "打开夹爪", "张开夹爪"}:
                self.open_gripper()
            elif normalized in {"close", "close gripper", "关闭", "闭合", "关闭夹爪", "闭合夹爪"}:
                self.close_gripper()
            elif normalized in {"above", "move above", "到物体上方", "移动到物体上方", "上方"}:
                self.move_above_object()
            elif normalized in {"approach", "down", "下降", "接近", "靠近物体", "下降接近"}:
                self.approach_object()
            elif normalized in {"pick", "grasp", "pick object", "抓取", "抓住", "拿起", "抓取物体", "抓起物体", "拿起物体"}:
                self.pick()
            elif normalized in {"lift", "up", "lift object", "抬起", "上升", "抬起物体", "向上抬起物体"}:
                self.lift()
            elif normalized in {"release", "drop", "放开", "松开", "放下物体", "松开物体"}:
                self.release()
            elif normalized.startswith(("place", "放到", "放置")) or "放到" in normalized or "放置" in normalized:
                self.place(_parse_place_target(normalized, self.object_home))
            elif normalized.startswith(("move ", "移动 ")):
                self.move_to(_parse_xyz_from_command(text))
            elif normalized.startswith(("delta ", "相对移动 ")):
                self.move_delta(_parse_xyz_from_command(text))
            elif _is_direction_command(normalized):
                self.move_delta(_parse_direction_delta(normalized))
            elif normalized in {"status", "状态"}:
                self.print_status()
            else:
                print(f"无法理解指令：{command}")
                print("输入 help 查看可用命令。")
                self.last_command_status = "failed"
                self.last_error = f"Unknown command: {command}"
                return False
            self.print_status(short=True)
            self.last_command_status = "completed"
            return True
        except CommandCancelled:
            self.hold_position()
            self.last_command_status = "cancelled"
            self.last_error = "Command cancelled by user"
            print("Command cancelled.")
            return False
        except Exception as exc:
            print(f"执行失败：{exc}")
            self.last_command_status = "failed"
            self.last_error = str(exc)
            return False

    def print_help(self):
        print(
            "\n可用指令：\n"
            "  help / 帮助\n"
            "  home / 复位\n"
            "  open / 打开夹爪\n"
            "  close / 关闭夹爪\n"
            "  above / 到物体上方\n"
            "  approach / 下降接近\n"
            "  pick / 抓取\n"
            "  lift / 抬起\n"
            "  release / 放开\n"
            "  place left|right|front|back / 放到左边|右边|前面|后面\n"
            "  move x y z / 移动 x y z\n"
            "  delta dx dy dz / 相对移动 dx dy dz\n"
            "  status / 状态\n"
            "  quit / 退出\n"
        )

    def home(self):
        self._move_joint_targets_visual(self.robot.home_pose, self.target_steps)
        self.robot.open_gripper()
        self.idle(20)

    def reset_scene(self):
        """Return the robot and manipulated object to their configured start poses."""
        self._remove_grasp_constraint()
        self.grasped = False
        for item in self.scene_objects.values():
            self.p.resetBasePositionAndOrientation(
                item["body_id"],
                item["home_position"],
                item["home_orientation"],
            )
            self.p.resetBaseVelocity(item["body_id"], [0, 0, 0], [0, 0, 0])
        self.object_pos = self.object_home.copy()
        self.home()

    def set_active_object(self, object_id: str):
        """Select which independent scene body subsequent object actions address."""
        object_id = str(object_id).strip()
        if object_id not in self.scene_objects:
            raise ActionFeasibilityError(f"unknown scene object: {object_id}")
        if self.grasped and object_id != self.active_object_id:
            raise ActionFeasibilityError("release the grasped object before changing Active Object")
        self._activate_object(object_id)
        self.last_action_details = {
            "operation": "set_active_object",
            "feasible": True,
            "summary": f"active object: {self.scene_objects[object_id]['label']}",
            "reasons": [],
            "metrics": {"active_object_id": object_id},
        }

    def open_gripper(self):
        self._remove_grasp_constraint()
        self.robot.open_gripper()
        self.grasped = False
        self.last_grasp_contact_summary = None
        self.idle(30)

    def close_gripper(self):
        self.robot.close_gripper(force=self.grasp_force)
        self._wait_for_force_closure()

    def move_above_object(self):
        target = self._object_grasp_point() + np.array([0, 0, self.above_offset], dtype=float)
        self._move_grasp_to(target)

    def approach_object(self):
        self._move_grasp_to(self._object_grasp_point())

    def assess_action(
        self,
        operation: str,
        target: np.ndarray | None = None,
        target_orientation: np.ndarray | None = None,
    ) -> dict:
        """Evaluate an action from geometry, dynamics, reach, and grasp state."""
        aliases = {
            "move_to": "move_to",
            "place_at": "place_at",
            "push_to": "push_to",
            "rotate_to": "rotate_to",
            "pick": "pick",
        }
        operation = aliases.get(operation, operation)
        reasons = []
        target_array = None if target is None else np.asarray(target, dtype=float)
        lower, upper = (np.asarray(value, dtype=float) for value in self.p.getAABB(self.object_id))
        object_position, _ = self.env.get_body_pose(self.object_id)
        dimensions = upper - lower
        mass = float(self.p.getDynamicsInfo(self.object_id, -1)[0])
        active_item = self.scene_objects[self.active_object_id]
        mass_property = self.object_properties.get("mass_kg", {})
        friction_property = self.object_properties.get("friction", {})
        metrics = {
            "active_object_id": self.active_object_id,
            "active_object_label": active_item.get("label", self.active_object_id),
            "object_dynamic": bool(active_item.get("dynamic", True)),
            "object_dimensions_m": dimensions.tolist(),
            "object_mass_kg": mass,
            "gripper_opening_m": self.gripper_max_object_width,
            "property_status": self.object_properties.get("property_status", "configured"),
            "mass_confidence": float(mass_property.get("confidence", 1.0)),
            "friction_confidence": float(friction_property.get("confidence", 1.0)),
        }

        if operation == "pick":
            if not active_item.get("dynamic", True):
                reasons.append("active object is static")
            metrics["axis_aligned_widths_m"] = dimensions.tolist()
            if mass > self.max_payload_mass:
                reasons.append(
                    f"object mass {mass:.2f} kg exceeds payload {self.max_payload_mass:.2f} kg"
                )
            if active_item.get("dynamic", True) and mass <= self.max_payload_mass:
                self.last_grasp_plan = self.grasp_planner.plan()
                metrics.update(
                    {
                        "grasp_planner": self.last_grasp_plan["source"],
                        "grasp_geometric_candidates": self.last_grasp_plan[
                            "geometric_candidate_count"
                        ],
                        "grasp_evaluated_candidates": self.last_grasp_plan[
                            "evaluated_candidate_count"
                        ],
                        "grasp_valid_candidates": self.last_grasp_plan["valid_candidate_count"],
                    }
                )
                if not self.last_grasp_plan["candidates"]:
                    reasons.append(
                        "no collision-free antipodal grasp satisfies gripper width and IK limits"
                    )
                else:
                    best = serialize_grasp(self.last_grasp_plan["candidates"][0])
                    metrics["selected_grasp"] = best
            else:
                self.last_grasp_plan = None

        elif operation == "move_to":
            if target_array is None:
                reasons.append("target position is required")
            else:
                adjusted = target_array.copy()
                adjusted[2] = max(adjusted[2], self.minimum_end_effector_z)
                metrics["evaluated_target_m"] = adjusted.tolist()
                if not self._position_reachable(adjusted):
                    reasons.append("target is outside the robot workspace")
                elif not self.grasped:
                    joint_targets = self.robot.inverse_kinematics(adjusted)
                    collision_free = self._joint_path_collision_free(joint_targets)
                    metrics["collision_free_path"] = collision_free
                    if not collision_free:
                        reasons.append(
                            "Move EE path would contact a scene object; use Push for intentional contact"
                        )

        elif operation == "place_at":
            if not self.grasped or self.grasp_constraint_id is None:
                reasons.append("place requires a valid bilateral grasp")
            if target_array is None:
                reasons.append("target position is required")
            else:
                supported_target = self._project_object_target_to_support(target_array)
                metrics["supported_target_m"] = supported_target.tolist()
                if not self._position_reachable(supported_target + np.array([0.0, 0.0, 0.14])):
                    reasons.append("target support location is outside the robot workspace")

        elif operation == "rotate_to":
            if not self.grasped or self.grasp_constraint_id is None:
                reasons.append("rotation requires a valid bilateral grasp")
            if target_orientation is None:
                reasons.append("target orientation is required")

        elif operation == "push_to":
            if not active_item.get("dynamic", True):
                reasons.append("active object is static")
            if self.grasped:
                reasons.append("release the grasped object before pushing")
            if target_array is None:
                reasons.append("target position is required")
            else:
                displacement = target_array[:2] - object_position[:2]
                push_distance = float(np.linalg.norm(displacement))
                required_force = self.object_friction * mass * 9.81
                minimum_mass = float(mass_property.get("min", mass))
                maximum_mass = float(mass_property.get("max", mass))
                minimum_friction = float(friction_property.get("min", self.object_friction))
                maximum_friction = float(friction_property.get("max", self.object_friction))
                support_z = self._support_surface_z(object_position)
                metrics.update(
                    {
                        "push_distance_m": push_distance,
                        "estimated_start_force_n": required_force,
                        "safe_push_force_n": self.max_safe_push_force,
                        "estimated_start_force_range_n": [
                            minimum_mass * minimum_friction * 9.81,
                            maximum_mass * maximum_friction * 9.81,
                        ],
                        "support_z_m": support_z,
                    }
                )
                if push_distance < 0.015:
                    reasons.append("object is already within target tolerance")
                if push_distance > 0.40:
                    reasons.append("target is beyond the fixed-base robot push range")
                if lower[2] > support_z + 0.025:
                    reasons.append("object is not resting on a known support surface")
                if required_force > self.max_safe_push_force:
                    reasons.append(
                        f"estimated start force {required_force:.1f} N exceeds safe push force "
                        f"{self.max_safe_push_force:.1f} N"
                    )
                if push_distance >= 0.015:
                    plan = self._plan_push(target_array)
                    if plan is None:
                        reasons.append(
                            "no physical collision surface was found for the requested push direction"
                        )
                    else:
                        neutral_path_clear = self._joint_path_collision_free(
                            self.robot.home_pose
                        )
                        metrics["neutral_transition_collision_free"] = neutral_path_clear
                        if not neutral_path_clear:
                            reasons.append(
                                "robot cannot reach its neutral push posture without object contact"
                            )
                        metrics.update(
                            {
                                "planned_surface_contact_m": plan["surface_contact"].tolist(),
                                "planned_contact_m": plan["contact_target"].tolist(),
                                "planned_contact_normal": plan["surface_normal"].tolist(),
                                "planned_wrist_roll_offset_deg": float(
                                    np.rad2deg(plan["orientation_roll_offset_rad"])
                                ),
                            }
                        )
                        pose_checks = (
                            ("pre-contact", plan["pre_contact"]),
                            ("contact", plan["contact_target"]),
                            ("push endpoint", plan["path_end"]),
                        )
                        for label, pose in pose_checks:
                            check = self._pose_reachability(
                                pose,
                                plan["orientation"],
                                rest_positions=self._home_joint_positions(),
                            )
                            metrics[f"{label.replace(' ', '_')}_position_error_m"] = check[
                                "position_error_m"
                            ]
                            metrics[f"{label.replace(' ', '_')}_orientation_error_deg"] = check[
                                "orientation_error_deg"
                            ]
                            if not check["reachable"]:
                                if check.get("reason"):
                                    reasons.append(f"planned {label} pose {check['reason']}")
                                else:
                                    reasons.append(
                                        f"planned {label} pose is not reachable "
                                        f"({check['position_error_m']:.3f} m / "
                                        f"{check['orientation_error_deg']:.1f} deg IK error)"
                                    )
        else:
            reasons.append(f"unsupported feasibility operation: {operation}")

        feasible = not reasons
        summary = f"{operation}: feasible" if feasible else f"{operation}: " + "; ".join(reasons)
        return {
            "operation": operation,
            "feasible": feasible,
            "summary": summary,
            "reasons": reasons,
            "metrics": metrics,
        }

    def _require_feasible(
        self,
        operation: str,
        target: np.ndarray | None = None,
        target_orientation: np.ndarray | None = None,
    ) -> dict:
        details = self.assess_action(operation, target, target_orientation)
        self.last_action_details = details
        if not details["feasible"]:
            raise ActionFeasibilityError(details["summary"])
        return details

    def pick(self):
        details = self._require_feasible("pick")
        candidates = (self.last_grasp_plan or {}).get("candidates", [])
        failures = []
        for attempt, candidate in enumerate(candidates[:3], start=1):
            try:
                self._move_grasp_pose(
                    candidate["pregrasp_position"],
                    candidate["orientation"],
                )
                self.robot.open_gripper()
                self.idle(20)
                self._move_grasp_pose(
                    candidate["position"],
                    candidate["orientation"],
                    position_tolerance=0.045,
                    joint_tolerance=0.14,
                )
                self.close_gripper()
                details["summary"] = (
                    f"pick: grasp {attempt} succeeded with score {candidate['score']:.3f}"
                )
                details["metrics"]["executed_grasp"] = serialize_grasp(candidate)
                details["metrics"]["grasp_attempts"] = attempt
                self.last_action_details = details
                return
            except (GraspFailure, MotionSafetyError) as exc:
                failures.append(str(exc))
                self._remove_grasp_constraint()
                self.grasped = False
                self.robot.open_gripper()
                self.idle(20)
        details["feasible"] = False
        details["reasons"].append("physical validation failed for the highest-ranked grasps")
        details["metrics"]["grasp_attempt_failures"] = failures
        details["summary"] = "pick: " + "; ".join(failures[-3:])
        self.last_action_details = details
        raise GraspFailure(details["summary"])

    def lift(self):
        if not self.grasped or self.grasp_constraint_id is None:
            raise GraspFailure("Cannot lift: no bilateral finger contact")
        current, orientation = self.robot.get_grasp_pose()
        target = current + np.array([0, 0, 0.18], dtype=float)
        self._move_grasp_pose(
            target,
            orientation,
            position_tolerance=0.045,
            joint_tolerance=0.16,
        )

    def release(self):
        self._remove_grasp_constraint()
        self.robot.open_gripper()
        self.grasped = False
        self.last_grasp_contact_summary = None
        self._settle_released_object()

    def place(self, target: np.ndarray, target_orientation: np.ndarray | None = None):
        self._require_feasible("place_at", target, target_orientation)
        target = self._project_object_target_to_support(np.asarray(target, dtype=float))
        current_grasp, current_grasp_orientation = self.robot.get_grasp_pose()
        current_object, _ = self.env.get_body_pose(self.object_id)
        displacement = target - current_object
        self._move_grasp_pose(
            current_grasp + displacement + np.array([0, 0, 0.14], dtype=float),
            current_grasp_orientation,
        )
        if target_orientation is not None:
            self.rotate_object_to(target_orientation, check_feasibility=False)
        current_grasp, current_grasp_orientation = self.robot.get_grasp_pose()
        current_object, _ = self.env.get_body_pose(self.object_id)
        place_grasp = current_grasp + (target - current_object)
        self._move_grasp_pose(place_grasp, current_grasp_orientation)
        self.release()
        self._move_grasp_pose(
            place_grasp + np.array([0, 0, 0.18], dtype=float),
            current_grasp_orientation,
        )
        placed_position, placed_orientation = self.env.get_body_pose(self.object_id)
        position_error = float(np.linalg.norm(placed_position[:2] - target[:2]))
        orientation_error = (
            self._quaternion_angle(placed_orientation, target_orientation)
            if target_orientation is not None
            else 0.0
        )
        self.last_action_details = {
            "operation": "place_at",
            "feasible": True,
            "summary": (
                f"place_at: position error {position_error:.3f} m; "
                f"orientation error {np.rad2deg(orientation_error):.1f} deg"
            ),
            "reasons": [],
            "metrics": {
                "position_error_m": position_error,
                "orientation_error_deg": float(np.rad2deg(orientation_error)),
                "supported_target_m": target.tolist(),
            },
        }

    def rotate_object_to(self, target_orientation: np.ndarray, check_feasibility: bool = True):
        target_orientation = self._normalized_quaternion(target_orientation)
        if check_feasibility:
            self._require_feasible("rotate_to", target_orientation=target_orientation)
        grasp_position, grasp_orientation = self.robot.get_grasp_pose()
        object_position, object_orientation = self.env.get_body_pose(self.object_id)
        inverse_grasp_position, inverse_grasp_orientation = self.p.invertTransform(
            grasp_position,
            grasp_orientation,
        )
        relative_position, relative_orientation = self.p.multiplyTransforms(
            inverse_grasp_position,
            inverse_grasp_orientation,
            object_position,
            object_orientation,
        )
        inverse_relative_position, inverse_relative_orientation = self.p.invertTransform(
            relative_position,
            relative_orientation,
        )
        target_grasp_position, target_grasp_orientation = self.p.multiplyTransforms(
            object_position,
            target_orientation,
            inverse_relative_position,
            inverse_relative_orientation,
        )
        desired_joint_map = self.robot.inverse_kinematics(
            target_grasp_position,
            target_grasp_orientation,
            link_index=self.robot.grasp_link_index,
        )
        current_joints, _ = self.robot.get_arm_state()
        desired_joints = np.array(
            [
                desired_joint_map.get(name, current_joints[index])
                for index, name in enumerate(self.robot.arm_joint_names)
            ],
            dtype=float,
        )
        stable_steps = 0
        peak_moment = 0.0
        for _ in range(1200):
            _, actual_orientation = self.env.get_body_pose(self.object_id)
            angle_error = self._quaternion_angle(actual_orientation, target_orientation)
            stable_steps = stable_steps + 1 if angle_error < np.deg2rad(5.0) else 0
            if stable_steps >= 12:
                break
            inverse_actual = self.p.invertTransform([0.0, 0.0, 0.0], actual_orientation)[1]
            _, error_orientation = self.p.multiplyTransforms(
                [0.0, 0.0, 0.0],
                target_orientation,
                [0.0, 0.0, 0.0],
                inverse_actual,
            )
            axis, signed_angle = self.p.getAxisAngleFromQuaternion(error_orientation)
            axis = np.asarray(axis, dtype=float)
            if signed_angle > np.pi:
                signed_angle = 2.0 * np.pi - signed_angle
                axis = -axis
            moment_magnitude = min(6.0, max(0.4, 5.0 * float(signed_angle)))
            peak_moment = max(peak_moment, moment_magnitude)
            joint_position, joint_velocity = self.robot.get_arm_state()
            acceleration = (
                0.35 * self.arm_kp * (desired_joints - joint_position)
                - self.arm_kd * joint_velocity
            )
            acceleration = np.clip(acceleration, -45.0, 45.0)
            torques = self.robot.inverse_dynamics(acceleration)
            _, angular_jacobian = self.robot.jacobian(self.robot.grasp_link_index)
            torques += angular_jacobian.T @ (axis * moment_magnitude)
            self.robot.apply_arm_torques(torques)
            self._step_simulation(apply_hold=False)
            unsafe_link = self._table_penetrating_link()
            if unsafe_link is not None:
                self.hold_position()
                raise MotionSafetyError(
                    f"Rotation stopped before {unsafe_link} crossed the support surface"
                )
        self.hold_position()
        _, actual_orientation = self.env.get_body_pose(self.object_id)
        angle_error = self._quaternion_angle(actual_orientation, target_orientation)
        if angle_error > np.deg2rad(8.0):
            raise MotionSafetyError(f"Object orientation error is too large: {np.rad2deg(angle_error):.1f} deg")
        self.last_action_details = {
            "operation": "rotate_to",
            "feasible": True,
            "summary": f"rotate_to: completed with {np.rad2deg(angle_error):.1f} deg error",
            "reasons": [],
            "metrics": {
                "orientation_error_deg": float(np.rad2deg(angle_error)),
                "peak_commanded_moment_nm": peak_moment,
            },
        }

    def push_to(self, target: np.ndarray):
        target = np.asarray(target, dtype=float)
        details = self._require_feasible("push_to", target)
        self.robot.close_gripper(force=10.0)
        self.idle(30)
        self._move_to_neutral_push_posture()

        object_start, _ = self.env.get_body_pose(self.object_id)
        displacement = target[:2] - object_start[:2]
        push_distance = float(np.linalg.norm(displacement))
        direction = displacement / push_distance
        plan = self._plan_push(target)
        if plan is None:
            raise ActionFeasibilityError(
                "push_to: collision surface disappeared before the motion started"
            )
        push_orientation = plan["orientation"]
        pre_contact = plan["pre_contact"]
        contact_target = plan["contact_target"]
        self._move_grasp_pose(pre_contact, push_orientation)
        peak_force = 0.0
        peak_horizontal_force = 0.0
        peak_directional_force = 0.0
        peak_downward_force = 0.0
        established_contact = False
        for alpha in np.linspace(0.25, 1.0, 4):
            approach = (1.0 - alpha) * pre_contact + alpha * contact_target
            self._move_grasp_pose(
                approach,
                push_orientation,
                position_tolerance=0.065,
                joint_tolerance=0.16,
            )
            contact = self._robot_object_contact_summary()
            peak_force = max(peak_force, contact["force"])
            peak_horizontal_force = max(peak_horizontal_force, contact["horizontal_force"])
            peak_downward_force = max(
                peak_downward_force,
                max(0.0, -float(contact["force_on_object"][2])),
            )
            peak_directional_force = max(
                peak_directional_force,
                max(
                    0.0,
                    float(np.dot(np.asarray(contact["force_on_object"][:2]), direction)),
                ),
            )
            if contact["count"] > 0 and contact["force"] >= 0.02:
                established_contact = True
                break
        if not established_contact:
            closest = self.p.getClosestPoints(self.robot.body_id, self.object_id, distance=0.20)
            minimum_distance = min((point[8] for point in closest), default=float("inf"))
            raise ActionFeasibilityError(
                f"push_to: robot did not establish physical contact; closest distance "
                f"{minimum_distance:.3f} m"
            )

        grasp_position, _ = self.robot.get_grasp_pose()
        desired_grasp_position = grasp_position + np.array(
            [direction[0] * (push_distance + 0.08), direction[1] * (push_distance + 0.08), 0.0]
        )
        desired_joint_map = self.robot.inverse_kinematics(
            desired_grasp_position,
            push_orientation,
            link_index=self.robot.grasp_link_index,
        )
        current_joints, _ = self.robot.get_arm_state()
        desired_joints = np.array(
            [
                desired_joint_map.get(name, current_joints[index])
                for index, name in enumerate(self.robot.arm_joint_names)
            ],
            dtype=float,
        )
        required_force = float(details["metrics"]["estimated_start_force_n"])
        commanded_push_force = min(
            self.max_safe_push_force,
            max(5.0, required_force * 1.5 + 1.0),
        )
        no_contact_steps = 0
        for _ in range(960):
            object_position, _ = self.env.get_body_pose(self.object_id)
            remaining_vector = target[:2] - object_position[:2]
            remaining = float(np.linalg.norm(remaining_vector))
            if remaining <= 0.035:
                break
            joint_position, joint_velocity = self.robot.get_arm_state()
            acceleration = (
                0.45 * self.arm_kp * (desired_joints - joint_position)
                - self.arm_kd * joint_velocity
            )
            acceleration = np.clip(acceleration, -50.0, 50.0)
            torques = self.robot.inverse_dynamics(acceleration)
            jacobian = self.robot.linear_jacobian(self.robot.grasp_link_index)
            cartesian_force = np.array(
                [
                    direction[0] * commanded_push_force,
                    direction[1] * commanded_push_force,
                    0.0,
                ]
            )
            torques += jacobian.T @ cartesian_force
            self.robot.apply_arm_torques(torques)
            self._step_simulation(apply_hold=False)
            unsafe_link = self._table_penetrating_link()
            if unsafe_link is not None:
                self.hold_position()
                raise MotionSafetyError(f"Push stopped before {unsafe_link} crossed the support surface")
            contact = self._robot_object_contact_summary()
            peak_force = max(peak_force, contact["force"])
            peak_horizontal_force = max(peak_horizontal_force, contact["horizontal_force"])
            peak_downward_force = max(
                peak_downward_force,
                max(0.0, -float(contact["force_on_object"][2])),
            )
            peak_directional_force = max(
                peak_directional_force,
                max(
                    0.0,
                    float(np.dot(np.asarray(contact["force_on_object"][:2]), direction)),
                ),
            )
            no_contact_steps = no_contact_steps + 1 if contact["count"] == 0 else 0
            if no_contact_steps >= 60:
                break

        self.hold_position()

        object_end, _ = self.env.get_body_pose(self.object_id)
        final_error = float(np.linalg.norm(target[:2] - object_end[:2]))
        actual_displacement = float(np.linalg.norm(object_end[:2] - object_start[:2]))
        if actual_displacement < 0.01:
            table_id = self.env.body_ids.get("table")
            support_contacts = (
                self.p.getContactPoints(self.object_id, table_id)
                if table_id is not None
                else self.p.getContactPoints(self.object_id, self.env._ground)
            )
            support_normal = float(sum(contact[9] for contact in support_contacts))
            support_friction = float(
                sum(abs(contact[10]) + abs(contact[12]) for contact in support_contacts)
            )
            raise ActionFeasibilityError(
                f"push_to: peak contact {peak_force:.2f} N "
                f"({peak_horizontal_force:.2f} N horizontal, "
                f"{peak_directional_force:.2f} N toward target, "
                f"{peak_downward_force:.2f} N downward); support reaction was "
                f"{support_normal:.2f} N normal / {support_friction:.2f} N friction; "
                f"object moved only {actual_displacement:.3f} m"
            )
        if final_error > 0.06:
            raise ActionFeasibilityError(
                f"push_to: contact moved the object {actual_displacement:.3f} m but target "
                f"error remains {final_error:.3f} m"
            )

        grasp_position, grasp_orientation = self.robot.get_grasp_pose()
        retreat = grasp_position + np.array(
            [-direction[0] * 0.08, -direction[1] * 0.08, 0.08]
        )
        self._move_grasp_pose(retreat, grasp_orientation)
        self.idle(60)
        details["summary"] = (
            f"push_to: moved {actual_displacement:.3f} m; target error {final_error:.3f} m"
        )
        details["metrics"].update(
            {
                "actual_displacement_m": actual_displacement,
                "target_error_m": final_error,
                "peak_contact_force_n": peak_force,
                "peak_horizontal_force_n": peak_horizontal_force,
                "peak_directional_force_n": peak_directional_force,
                "peak_downward_force_n": peak_downward_force,
                "commanded_push_force_n": commanded_push_force,
            }
        )
        self.last_action_details = details

    def move_delta(self, delta: np.ndarray):
        current, _ = self.robot.get_end_effector_pose()
        self.move_to(current + delta)

    def move_to(self, target: np.ndarray):
        target = np.asarray(target, dtype=float).copy()
        if target[2] < self.minimum_end_effector_z:
            print(
                f"Safety clamp: end-effector z {target[2]:.3f} -> "
                f"{self.minimum_end_effector_z:.3f}"
            )
            target[2] = self.minimum_end_effector_z
        self._move_robot_visual(target, self.target_steps)

    def idle(self, steps: int):
        for _ in range(steps):
            self._step_simulation()

    def print_status(self, short: bool = False):
        ee_pos, _ = self.robot.get_end_effector_pose()
        obj_pos, _ = self.env.get_body_pose(self.object_id)
        self.object_pos = obj_pos
        if short:
            print(
                "状态："
                f"末端={_fmt_vec(ee_pos)} "
                f"物体={_fmt_vec(obj_pos)} "
                f"抓取={'是' if self.grasped else '否'}"
            )
            return
        print(f"末端位置: {_fmt_vec(ee_pos)}")
        print(f"物体位置: {_fmt_vec(obj_pos)}")
        print(f"夹爪开度: {self.robot.get_gripper_opening():.3f}")
        print(f"是否抓取: {'是' if self.grasped else '否'}")

    def close(self):
        self._remove_grasp_constraint()
        self.env.disconnect()

    def _load_object(self) -> int:
        if self.object_path and self.object_path.exists():
            return self.env.load_object(
                self.object_path,
                self.object_home,
                scale=self.object_scale,
                mass=self.object_mass,
            )
        if self.object_path:
            print(f"WARNING: {self.object_path} not found, using demo box")
        return _load_demo_box(self.p, self.object_home)

    def _load_scene_objects(self):
        if self.scene_manifest_path is None:
            body_id = self._load_object()
            self.active_object_id = "object"
            self.scene_objects = {
                "object": {
                    "id": "object",
                    "label": self.object_path.stem if self.object_path else "demo_object",
                    "body_id": body_id,
                    "source_path": str(self.object_path.resolve()) if self.object_path else None,
                    "scale": float(self.object_scale),
                    "mass_kg": float(self.object_mass),
                    "friction": float(self.object_friction),
                    "dynamic": True,
                    "properties": {
                        "mass_kg": {
                            "min": float(self.object_mass),
                            "estimate": float(self.object_mass),
                            "max": float(self.object_mass),
                            "source": "command_line",
                            "confidence": 1.0,
                        },
                        "friction": {
                            "min": float(self.object_friction),
                            "estimate": float(self.object_friction),
                            "max": float(self.object_friction),
                            "source": "command_line",
                            "confidence": 1.0,
                        },
                        "property_status": "configured",
                        "simulation_only": True,
                    },
                }
            }
        else:
            self.prepared_manifest = load_scene_manifest(self.scene_manifest_path)
            self.scene_objects = {}
            for spec in self.prepared_manifest["objects"]:
                body_id = self.env.load_object(
                    spec["source_path"],
                    spec["position"],
                    scale=spec["scale"],
                    mass=spec["mass_kg"] if spec["dynamic"] else 0.0,
                )
                self.p.resetBasePositionAndOrientation(
                    body_id,
                    spec["position"],
                    spec["orientation"],
                )
                self.scene_objects[spec["id"]] = {
                    **spec,
                    "body_id": body_id,
                    "source_path": str(Path(spec["source_path"]).resolve()),
                }
            self.active_object_id = self.prepared_manifest["active_object_id"]

        if self.scene_profile == "floor":
            for item in self.scene_objects.values():
                position, orientation = self.env.get_body_pose(item["body_id"])
                lower, _ = self.p.getAABB(item["body_id"])
                position[2] += 0.002 - lower[2]
                self.p.resetBasePositionAndOrientation(item["body_id"], position, orientation)
                self.p.resetBaseVelocity(item["body_id"], [0, 0, 0], [0, 0, 0])
        for item in self.scene_objects.values():
            self._configure_body_dynamics(item)

    def _activate_object(self, object_id: str | None, initial: bool = False):
        if object_id is None or object_id not in self.scene_objects:
            raise ActionFeasibilityError("scene has no valid Active Object")
        item = self.scene_objects[object_id]
        self.active_object_id = object_id
        self.object_id = item["body_id"]
        source = item.get("source_path")
        self.object_path = Path(source) if source else None
        self.object_scale = float(item.get("scale", 1.0))
        self.object_mass = float(item.get("mass_kg", 0.5))
        self.object_friction = float(item.get("friction", 0.5))
        self.object_properties = dict(item.get("properties") or {})
        self.last_grasp_plan = None
        if "home_position" in item:
            self.object_home = np.asarray(item["home_position"], dtype=float).copy()
            self.object_home_orientation = np.asarray(item["home_orientation"], dtype=float).copy()
            self.object_support_offset = float(item.get("support_offset", 0.025))
            self.object_pos = self.object_home.copy()
        elif not initial:
            self.object_home, self.object_home_orientation = self.env.get_body_pose(self.object_id)

    def _configure_scene_collisions(self):
        """Enable physical contact between the robot, object, and table."""
        table_id = self.env.body_ids.get("table")
        for link_idx in range(-1, self.p.getNumJoints(self.robot.body_id)):
            for item in self.scene_objects.values():
                self.p.setCollisionFilterPair(
                    self.robot.body_id,
                    item["body_id"],
                    link_idx,
                    -1,
                    1,
                )
            if table_id is not None:
                self.p.setCollisionFilterPair(self.robot.body_id, table_id, link_idx, -1, 1)

    def _move_robot_visual(self, target_pos: np.ndarray, steps: int):
        joint_targets = self.robot.inverse_kinematics(target_pos)
        if not self.grasped and not self._joint_path_collision_free(joint_targets):
            raise MotionSafetyError(
                "Move EE path would contact a scene object; use Push for intentional contact"
            )
        self._move_joint_targets_visual(
            joint_targets,
            steps,
            final_joint_tolerance=None if self.grasped else 0.10,
            forbid_object_contact=not self.grasped,
        )
        actual_position, _ = self.robot.get_end_effector_pose()
        cartesian_error = float(np.linalg.norm(actual_position - np.asarray(target_pos, dtype=float)))
        if cartesian_error > 0.04:
            raise MotionSafetyError(
                f"End-effector target error is too large: {cartesian_error:.3f} m"
            )

    def _move_grasp_to(self, target_pos: np.ndarray):
        self._move_grasp_pose(target_pos, self.top_down_orientation)

    def _move_grasp_pose(
        self,
        target_pos: np.ndarray,
        target_orientation: np.ndarray,
        position_tolerance: float | None = 0.035,
        joint_tolerance: float | None = 0.10,
    ):
        target_pos = np.asarray(target_pos, dtype=float)
        target_orientation = self._normalized_quaternion(target_orientation)
        joint_targets = self.robot.inverse_kinematics(
            target_pos,
            target_orientation,
            link_index=self.robot.grasp_link_index,
        )
        self._move_joint_targets_visual(
            joint_targets,
            self.target_steps,
            final_joint_tolerance=joint_tolerance,
        )
        actual_pos, _ = self.robot.get_grasp_pose()
        error = float(np.linalg.norm(actual_pos - target_pos))
        if position_tolerance is not None and error > position_tolerance:
            raise MotionSafetyError(f"Grasp target tracking error is too large: {error:.3f} m")

    def _home_joint_positions(self) -> np.ndarray:
        return np.asarray(
            [self.robot.home_pose[name] for name in self.robot.arm_joint_names],
            dtype=float,
        )

    def _move_to_neutral_push_posture(self):
        """Enter a deterministic collision-checked posture before contact planning."""
        current, _ = self.robot.get_arm_state()
        home = self._home_joint_positions()
        if float(np.max(np.abs(home - current))) < 0.05:
            return
        if not self._joint_path_collision_free(self.robot.home_pose):
            raise MotionSafetyError(
                "Push aborted: path to the neutral push posture would contact a scene object"
            )
        self._move_joint_targets_visual(
            self.robot.home_pose,
            self.target_steps,
            final_joint_tolerance=0.10,
            forbid_object_contact=True,
        )

    def _move_joint_targets_visual(
        self,
        joint_targets: dict,
        steps: int,
        final_joint_tolerance: float | None = 0.10,
        forbid_object_contact: bool = False,
    ):
        """Track a quintic joint trajectory using inverse-dynamics torque control."""
        start, _ = self.robot.get_arm_state()
        target = np.array(
            [joint_targets.get(name, start[index]) for index, name in enumerate(self.robot.arm_joint_names)],
            dtype=float,
        )
        delta = target - start
        duration = float(np.clip(max(0.9, np.max(np.abs(delta)) / 0.7), 0.9, 4.0))
        trajectory_steps = max(int(steps), int(np.ceil(duration / self.dt)))
        duration = trajectory_steps * self.dt

        for step in range(1, trajectory_steps + 1):
            phase = step / trajectory_steps
            blend = 10 * phase**3 - 15 * phase**4 + 6 * phase**5
            blend_velocity = (30 * phase**2 - 60 * phase**3 + 30 * phase**4) / duration
            blend_acceleration = (60 * phase - 180 * phase**2 + 120 * phase**3) / (duration**2)
            desired_position = start + blend * delta
            desired_velocity = blend_velocity * delta
            desired_acceleration = blend_acceleration * delta
            self._apply_arm_controller(desired_position, desired_velocity, desired_acceleration)
            self._step_simulation(apply_hold=False)
            unsafe_link = self._table_penetrating_link()
            if unsafe_link is not None:
                self.hold_position()
                raise MotionSafetyError(
                    f"Torque motion stopped before {unsafe_link} crossed the support surface"
                )
            if forbid_object_contact and self._scene_contact_force() > 2.0:
                self.hold_position()
                raise MotionSafetyError(
                    "Move EE stopped after unexpected scene contact exceeded 2.0 N"
                )

        self.arm_hold_target = target.copy()
        stable_steps = 0
        for _ in range(240):
            self._step_simulation()
            final_position, final_velocity = self.robot.get_arm_state()
            joint_error = float(np.max(np.abs(target - final_position)))
            joint_speed = float(np.max(np.abs(final_velocity)))
            stable_steps = stable_steps + 1 if joint_error < 0.05 and joint_speed < 0.08 else 0
            if stable_steps >= 12:
                break
        final_position, _ = self.robot.get_arm_state()
        error = float(np.max(np.abs(target - final_position)))
        if final_joint_tolerance is not None and error > final_joint_tolerance:
            raise MotionSafetyError(f"Joint torque controller did not converge: {error:.3f} rad")

    def _joint_path_collision_free(self, joint_targets: dict, samples: int = 28) -> bool:
        states = self.p.getJointStates(self.robot.body_id, self.robot.arm_joint_indices)
        start = np.asarray([state[0] for state in states], dtype=float)
        velocities = np.asarray([state[1] for state in states], dtype=float)
        target = np.asarray(
            [
                joint_targets.get(name, start[index])
                for index, name in enumerate(self.robot.arm_joint_names)
            ],
            dtype=float,
        )
        collision_free = True
        try:
            for alpha in np.linspace(0.0, 1.0, samples):
                values = (1.0 - alpha) * start + alpha * target
                for index, joint_index in enumerate(self.robot.arm_joint_indices):
                    self.p.resetJointState(
                        self.robot.body_id,
                        joint_index,
                        float(values[index]),
                    )
                self.p.performCollisionDetection()
                if any(
                    self.p.getClosestPoints(
                        self.robot.body_id,
                        item["body_id"],
                        distance=0.002,
                    )
                    for item in self.scene_objects.values()
                ):
                    collision_free = False
                    break
        finally:
            for index, joint_index in enumerate(self.robot.arm_joint_indices):
                self.p.resetJointState(
                    self.robot.body_id,
                    joint_index,
                    float(start[index]),
                    targetVelocity=float(velocities[index]),
                )
            self.p.performCollisionDetection()
        return collision_free

    def _scene_contact_force(self) -> float:
        return float(
            sum(
                max(0.0, contact[9])
                for item in self.scene_objects.values()
                for contact in self.p.getContactPoints(self.robot.body_id, item["body_id"])
            )
        )

    def _apply_arm_controller(
        self,
        desired_position: np.ndarray,
        desired_velocity: np.ndarray | None = None,
        desired_acceleration: np.ndarray | None = None,
    ):
        position, velocity = self.robot.get_arm_state()
        desired_position = np.asarray(desired_position, dtype=float)
        desired_velocity = (
            np.zeros(7, dtype=float)
            if desired_velocity is None
            else np.asarray(desired_velocity, dtype=float)
        )
        desired_acceleration = (
            np.zeros(7, dtype=float)
            if desired_acceleration is None
            else np.asarray(desired_acceleration, dtype=float)
        )
        commanded_acceleration = (
            desired_acceleration
            + self.arm_kp * (desired_position - position)
            + self.arm_kd * (desired_velocity - velocity)
        )
        commanded_acceleration = np.clip(commanded_acceleration, -80.0, 80.0)
        torques = self.robot.inverse_dynamics(commanded_acceleration)
        if not np.all(np.isfinite(torques)):
            raise MotionSafetyError("Inverse dynamics produced non-finite torques")
        self.robot.apply_arm_torques(torques)

    def _step_simulation(self, apply_hold: bool = True):
        """Advance physics and expose the resulting frame to optional recorders."""
        if self.stop_event.is_set():
            raise CommandCancelled()
        if apply_hold and self.robot is not None and self.arm_hold_target is not None:
            self._apply_arm_controller(self.arm_hold_target)
        self.env.step()
        if self.grasped and self.robot is not None:
            self.last_grasp_contact_summary = self._finger_contact_summary()
        if self.frame_observer is not None:
            self.frame_observer(self)
        if self.step_delay > 0:
            time.sleep(self.step_delay)

    def request_stop(self):
        """Interrupt the current motion at the next physics step."""
        self.stop_event.set()

    def clear_stop(self):
        self.stop_event.clear()

    def hold_position(self):
        """Use gravity-compensated torque control to hold the current arm pose."""
        if self.robot is not None:
            self.arm_hold_target, _ = self.robot.get_arm_state()
            self._apply_arm_controller(self.arm_hold_target)

    def _wait_for_force_closure(self, max_steps: int = 180, stable_required: int = 8):
        stable_steps = 0
        last_summary = None
        for _ in range(max_steps):
            self._step_simulation()
            last_summary = self._finger_contact_summary()
            stable_steps = stable_steps + 1 if last_summary["valid"] else 0
            if stable_steps >= stable_required:
                self.last_grasp_contact_summary = last_summary
                self._create_grasp_constraint()
                self.grasped = True
                return

        self.robot.open_gripper()
        self.idle(30)
        self.last_grasp_contact_summary = last_summary
        raise GraspFailure("Grasp failed: both fingers did not establish opposing contact forces")

    def _finger_contact_summary(self) -> dict:
        fingers = []
        for link_idx in self.robot._finger_joints:
            contacts = [
                contact
                for contact in self.p.getContactPoints(
                    self.robot.body_id,
                    self.object_id,
                    linkIndexA=link_idx,
                    linkIndexB=-1,
                )
                if contact[9] >= self.minimum_contact_force
            ]
            force = float(sum(contact[9] for contact in contacts))
            if contacts and force > 0:
                weights = np.array([contact[9] for contact in contacts], dtype=float)
                points = np.array([contact[6] for contact in contacts], dtype=float)
                normals = np.array([contact[7] for contact in contacts], dtype=float)
                point = np.average(points, axis=0, weights=weights)
                normal = np.average(normals, axis=0, weights=weights)
                normal /= max(np.linalg.norm(normal), 1e-9)
            else:
                point = np.zeros(3, dtype=float)
                normal = np.zeros(3, dtype=float)
            fingers.append(
                {
                    "link_index": int(link_idx),
                    "count": len(contacts),
                    "force": force,
                    "point": point,
                    "normal": normal,
                }
            )

        opposing = False
        centered = False
        if all(finger["count"] > 0 for finger in fingers):
            opposing = float(np.dot(fingers[0]["normal"], fingers[1]["normal"])) < -0.5
            axis = fingers[1]["point"] - fingers[0]["point"]
            axis_length_sq = float(np.dot(axis, axis))
            if axis_length_sq > 1e-6:
                object_pos, _ = self.env.get_body_pose(self.object_id)
                interpolation = float(np.dot(object_pos - fingers[0]["point"], axis) / axis_length_sq)
                centered = -0.15 <= interpolation <= 1.15

        valid = bool(
            opposing
            and centered
            and all(finger["force"] >= self.minimum_contact_force for finger in fingers)
        )
        return {
            "valid": valid,
            "opposing_normals": opposing,
            "object_centered": centered,
            "fingers": [
                {
                    "link_index": finger["link_index"],
                    "count": finger["count"],
                    "force": finger["force"],
                    "point": finger["point"].tolist(),
                    "normal": finger["normal"].tolist(),
                }
                for finger in fingers
            ],
        }

    def _create_grasp_constraint(self):
        self._remove_grasp_constraint()
        grasp_pos, grasp_orn = self.robot.get_grasp_pose()
        object_pos, object_orn = self.env.get_body_pose(self.object_id)
        inverse_pos, inverse_orn = self.p.invertTransform(grasp_pos, grasp_orn)
        relative_pos, relative_orn = self.p.multiplyTransforms(
            inverse_pos,
            inverse_orn,
            object_pos,
            object_orn,
        )
        self.grasp_constraint_id = self.p.createConstraint(
            parentBodyUniqueId=self.robot.body_id,
            parentLinkIndex=self.robot.grasp_link_index,
            childBodyUniqueId=self.object_id,
            childLinkIndex=-1,
            jointType=self.p.JOINT_FIXED,
            jointAxis=[0, 0, 0],
            parentFramePosition=relative_pos,
            childFramePosition=[0, 0, 0],
            parentFrameOrientation=relative_orn,
            childFrameOrientation=[0, 0, 0, 1],
        )
        self.p.changeConstraint(
            self.grasp_constraint_id,
            maxForce=self.grasp_constraint_force,
            erp=0.35,
        )

    def _remove_grasp_constraint(self):
        if self.grasp_constraint_id is not None:
            try:
                self.p.removeConstraint(self.grasp_constraint_id)
            except self.p.error:
                pass
        self.grasp_constraint_id = None

    def _object_grasp_point(self) -> np.ndarray:
        """Use the visual/collision bounds center so non-centered models grasp correctly."""
        lower, upper = self.p.getAABB(self.object_id)
        return (np.asarray(lower, dtype=float) + np.asarray(upper, dtype=float)) / 2.0

    def _plan_push(self, target: np.ndarray) -> dict | None:
        """Plan a side push against a surface that exists in the collision mesh."""
        target = np.asarray(target, dtype=float)
        object_position, _ = self.env.get_body_pose(self.object_id)
        displacement = target[:2] - object_position[:2]
        push_distance = float(np.linalg.norm(displacement))
        if push_distance < 1e-8:
            return None

        direction = displacement / push_distance
        lower, upper = (
            np.asarray(value, dtype=float) for value in self.p.getAABB(self.object_id)
        )
        support_z = self._support_surface_z(object_position)
        preferred_height = float(
            np.clip(
                (lower[2] + upper[2]) / 2.0,
                support_z + 0.025,
                support_z
                + (0.16 if self.env.body_ids.get("table") is not None else 0.65),
            )
        )
        surface = self._find_push_surface(
            direction,
            lower,
            upper,
            preferred_height,
            support_z,
        )
        if surface is None:
            return None

        surface_contact, surface_normal = surface
        push_yaw = float(np.arctan2(direction[1], direction[0]))
        if self.env.body_ids.get("table") is not None or surface_contact[2] < support_z + 0.12:
            orientation = np.asarray(
                self.p.getQuaternionFromEuler([np.pi, 0.0, push_yaw]),
                dtype=float,
            )
        else:
            side_orientation = self.p.getQuaternionFromEuler([0.0, np.pi / 2, push_yaw])
            axial_roll = self.p.getQuaternionFromEuler([0.0, 0.0, np.pi])
            _, orientation = self.p.multiplyTransforms(
                [0.0, 0.0, 0.0],
                side_orientation,
                [0.0, 0.0, 0.0],
                axial_roll,
            )
            orientation = np.asarray(orientation, dtype=float)

        direction_3d = np.array([direction[0], direction[1], 0.0], dtype=float)
        pre_contact = surface_contact - direction_3d * 0.10
        contact_target = surface_contact + direction_3d * 0.012
        path_end = contact_target + direction_3d * (push_distance + 0.08)
        plan = {
            "direction": direction,
            "orientation": orientation,
            "surface_contact": surface_contact,
            "surface_normal": surface_normal,
            "pre_contact": pre_contact,
            "contact_target": contact_target,
            "path_end": path_end,
        }
        self._select_push_orientation(plan)
        return plan

    def _select_push_orientation(self, plan: dict):
        """Choose a wrist roll that keeps the same contact geometry within joint limits."""
        base_orientation = np.asarray(plan["orientation"], dtype=float)
        candidates = []
        for roll in (0.0, np.pi, np.pi / 2, -np.pi / 2):
            _, orientation = self.p.multiplyTransforms(
                [0.0, 0.0, 0.0],
                base_orientation,
                [0.0, 0.0, 0.0],
                self.p.getQuaternionFromEuler([0.0, 0.0, roll]),
            )
            checks = [
                self._pose_reachability(
                    pose,
                    orientation,
                    rest_positions=self._home_joint_positions(),
                )
                for pose in (
                    plan["pre_contact"],
                    plan["contact_target"],
                    plan["path_end"],
                )
            ]
            maximum_position_error = max(check["position_error_m"] for check in checks)
            maximum_orientation_error = max(check["orientation_error_deg"] for check in checks)
            reachable_count = sum(check["reachable"] for check in checks)
            score = (
                -reachable_count,
                maximum_position_error + np.deg2rad(maximum_orientation_error) * 0.02,
            )
            candidates.append((score, np.asarray(orientation, dtype=float), checks, roll))

        _, orientation, checks, roll = min(candidates, key=lambda item: item[0])
        plan["orientation"] = orientation
        plan["orientation_roll_offset_rad"] = float(roll)
        plan["orientation_pose_checks"] = checks

    def _find_push_surface(
        self,
        direction: np.ndarray,
        lower: np.ndarray,
        upper: np.ndarray,
        preferred_height: float,
        support_z: float,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Probe the actual collision proxy instead of assuming a solid AABB."""
        direction = np.asarray(direction, dtype=float)
        transverse = np.array([-direction[1], direction[0]], dtype=float)
        corners = np.array(
            [
                [x, y]
                for x in (lower[0], upper[0])
                for y in (lower[1], upper[1])
            ],
            dtype=float,
        )
        along = corners @ direction
        across = corners @ transverse
        near_distance = float(np.min(along))
        far_distance = float(np.max(along))
        across_center = float((np.min(across) + np.max(across)) / 2.0)
        across_span = max(0.01, float(np.max(across) - np.min(across)))

        minimum_height = max(float(lower[2]) + 0.008, support_z + 0.025)
        maximum_height = float(upper[2]) - 0.008
        if maximum_height <= minimum_height:
            minimum_height = maximum_height = float((lower[2] + upper[2]) / 2.0)
        height_samples = np.linspace(minimum_height, maximum_height, 11)
        height_samples = sorted(
            (float(value) for value in height_samples),
            key=lambda value: abs(value - preferred_height),
        )
        across_samples = across_center + across_span * np.array(
            [0.0, -0.15, 0.15, -0.30, 0.30, -0.43, 0.43],
            dtype=float,
        )

        ray_from = []
        ray_to = []
        sample_metadata = []
        for height in height_samples:
            for across_value in across_samples:
                start_xy = direction * (near_distance - 0.06) + transverse * across_value
                end_xy = direction * (far_distance + 0.02) + transverse * across_value
                ray_from.append([float(start_xy[0]), float(start_xy[1]), height])
                ray_to.append([float(end_xy[0]), float(end_xy[1]), height])
                sample_metadata.append((height, float(across_value)))

        candidates = []
        for result, (height, across_value) in zip(
            self.p.rayTestBatch(ray_from, ray_to), sample_metadata
        ):
            if int(result[0]) != self.object_id:
                continue
            point = np.asarray(result[3], dtype=float)
            normal = np.asarray(result[4], dtype=float)
            opposing = -float(np.dot(normal[:2], direction))
            if opposing < 0.10:
                continue
            height_error = abs(height - preferred_height) / max(0.05, maximum_height - minimum_height)
            across_error = abs(across_value - across_center) / across_span
            score = height_error + 0.45 * across_error + 0.35 * (1.0 - min(1.0, opposing))
            candidates.append((score, point, normal))

        if not candidates:
            return None
        _, point, normal = min(candidates, key=lambda item: item[0])
        return point, normal

    def _pose_reachability(
        self,
        position: np.ndarray,
        orientation: np.ndarray,
        position_tolerance: float = 0.055,
        orientation_tolerance_deg: float = 25.0,
        rest_positions: np.ndarray | None = None,
    ) -> dict:
        """Evaluate a constrained IK solution without changing the live scene state."""
        position = np.asarray(position, dtype=float)
        orientation = self._normalized_quaternion(orientation)
        if not self._position_reachable(position):
            distance = float(np.linalg.norm(position - self.robot_base))
            return {
                "reachable": False,
                "position_error_m": max(0.0, distance - 1.0),
                "orientation_error_deg": 0.0,
                "reason": f"is outside the coarse workspace ({distance:.3f} m from base)",
            }

        joint_states = self.p.getJointStates(
            self.robot.body_id,
            self.robot.arm_joint_indices,
        )
        current_joints = np.asarray([state[0] for state in joint_states], dtype=float)
        current_velocities = np.asarray([state[1] for state in joint_states], dtype=float)
        try:
            joint_map = self.robot.inverse_kinematics(
                position,
                orientation,
                link_index=self.robot.grasp_link_index,
                rest_positions=rest_positions,
            )
            for index, joint_index in enumerate(self.robot.arm_joint_indices):
                joint_name = self.robot.arm_joint_names[index]
                self.p.resetJointState(
                    self.robot.body_id,
                    joint_index,
                    float(joint_map.get(joint_name, current_joints[index])),
                )
            actual_position, actual_orientation = self.robot.get_grasp_pose()
            position_error = float(np.linalg.norm(actual_position - position))
            orientation_error_deg = float(
                np.rad2deg(self._quaternion_angle(actual_orientation, orientation))
            )
        finally:
            for index, joint_index in enumerate(self.robot.arm_joint_indices):
                self.p.resetJointState(
                    self.robot.body_id,
                    joint_index,
                    float(current_joints[index]),
                    targetVelocity=float(current_velocities[index]),
                )

        return {
            "reachable": bool(
                position_error <= position_tolerance
                and orientation_error_deg <= orientation_tolerance_deg
            ),
            "position_error_m": position_error,
            "orientation_error_deg": orientation_error_deg,
        }

    def _position_reachable(self, position: np.ndarray) -> bool:
        position = np.asarray(position, dtype=float)
        distance = float(np.linalg.norm(position - self.robot_base))
        return bool(0.10 <= distance <= 1.0 and position[2] >= -0.005)

    @staticmethod
    def _normalized_quaternion(orientation: np.ndarray) -> np.ndarray:
        orientation = np.asarray(orientation, dtype=float)
        if orientation.shape != (4,):
            raise ValueError("Orientation must be an XYZW quaternion")
        length = float(np.linalg.norm(orientation))
        if length < 1e-8:
            raise ValueError("Orientation quaternion cannot be zero")
        return orientation / length

    @staticmethod
    def _quaternion_angle(first: np.ndarray, second: np.ndarray) -> float:
        first = CommandScene._normalized_quaternion(first)
        second = CommandScene._normalized_quaternion(second)
        dot = float(np.clip(abs(np.dot(first, second)), 0.0, 1.0))
        return 2.0 * np.arccos(dot)

    @staticmethod
    def _quaternion_slerp(first: np.ndarray, second: np.ndarray, alpha: float) -> np.ndarray:
        first = CommandScene._normalized_quaternion(first)
        second = CommandScene._normalized_quaternion(second)
        dot = float(np.dot(first, second))
        if dot < 0.0:
            second = -second
            dot = -dot
        dot = float(np.clip(dot, -1.0, 1.0))
        if dot > 0.9995:
            return CommandScene._normalized_quaternion(first + alpha * (second - first))
        angle = np.arccos(dot)
        return (
            np.sin((1.0 - alpha) * angle) * first + np.sin(alpha * angle) * second
        ) / np.sin(angle)

    def _robot_object_contact_summary(self) -> dict:
        contacts = self.p.getContactPoints(self.robot.body_id, self.object_id)
        forces = np.array([max(0.0, contact[9]) for contact in contacts], dtype=float)
        total_force = float(forces.sum())
        if contacts and total_force > 0:
            normals = np.asarray([contact[7] for contact in contacts], dtype=float)
            normal = np.average(normals, axis=0, weights=forces)
            normal /= max(float(np.linalg.norm(normal)), 1e-9)
            force_on_object = np.sum(-normals * forces[:, None], axis=0)
        else:
            normal = np.zeros(3, dtype=float)
            force_on_object = np.zeros(3, dtype=float)
        return {
            "count": len(contacts),
            "force": total_force,
            "normal": normal.tolist(),
            "force_on_object": force_on_object.tolist(),
            "horizontal_force": float(np.linalg.norm(force_on_object[:2])),
        }

    def _configure_body_dynamics(self, item: dict):
        """Apply each entity's independently estimated physical properties."""
        self.p.changeDynamics(
            item["body_id"],
            -1,
            lateralFriction=float(item.get("friction", 0.5)),
            spinningFriction=0.03,
            rollingFriction=0.01,
            restitution=0.01,
            linearDamping=0.12,
            angularDamping=0.18,
            contactProcessingThreshold=0.001,
            ccdSweptSphereRadius=0.008,
        )

    def _configure_object_dynamics(self):
        self._configure_body_dynamics(self.scene_objects[self.active_object_id])

    def _table_penetrating_link(self) -> str | None:
        table_exists = self.env.body_ids.get("table") is not None
        minimum_z = (
            self.table_top_z + self.table_collision_margin
            if table_exists
            else -self.table_collision_margin
        )
        for link_idx in range(self.p.getNumJoints(self.robot.body_id)):
            lower, _ = self.p.getAABB(self.robot.body_id, link_idx)
            if lower[2] < minimum_z:
                return self.p.getJointInfo(self.robot.body_id, link_idx)[12].decode("utf-8")
        return None

    def _sanitize_object_target(self, target: np.ndarray) -> np.ndarray:
        result = np.asarray(target, dtype=float).copy()
        support_z = self._support_surface_z(result)
        result[2] = max(result[2], support_z + self.object_support_offset + 0.001)
        return result

    def _project_object_target_to_support(self, target: np.ndarray) -> np.ndarray:
        result = np.asarray(target, dtype=float).copy()
        support_z = self._support_surface_z(result)
        result[2] = support_z + self.object_support_offset + 0.001
        return result

    def _support_surface_z(self, position: np.ndarray) -> float:
        if (
            self.env.body_ids.get("table") is not None
            and -0.25 <= position[0] <= 1.25
            and -0.5 <= position[1] <= 0.5
        ):
            return self.table_top_z
        return 0.0

    def _settle_released_object(self, max_steps: int = 240):
        """Advance physics until the released object rests on its support surface."""
        stable_steps = 0
        for _ in range(max_steps):
            self._step_simulation()
            position, _ = self.env.get_body_pose(self.object_id)
            linear_velocity, angular_velocity = self.p.getBaseVelocity(self.object_id)
            lower, _ = self.p.getAABB(self.object_id)
            support_z = self._support_surface_z(position)
            near_support = lower[2] <= support_z + 0.004
            speed = np.linalg.norm(linear_velocity) + 0.1 * np.linalg.norm(angular_velocity)
            stable_steps = stable_steps + 1 if near_support and speed < 0.035 else 0
            if stable_steps >= 12:
                break

        position, orientation = self.env.get_body_pose(self.object_id)
        lower, _ = self.p.getAABB(self.object_id)
        support_z = self._support_surface_z(position)
        if lower[2] < support_z - 0.002:
            position[2] += support_z - lower[2] + 0.001
            self.p.resetBasePositionAndOrientation(self.object_id, position, orientation)
        self.p.resetBaseVelocity(self.object_id, [0, 0, 0], [0, 0, 0])
        self.object_pos, _ = self.env.get_body_pose(self.object_id)


def _load_demo_box(p, position: np.ndarray, mass: float = 0.08) -> int:
    half_extents = [0.025, 0.025, 0.025]
    collision = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents)
    visual = p.createVisualShape(
        p.GEOM_BOX,
        halfExtents=half_extents,
        rgbaColor=[0.9, 0.12, 0.1, 1.0],
    )
    obj_id = p.createMultiBody(
        baseMass=float(mass),
        baseCollisionShapeIndex=collision,
        baseVisualShapeIndex=visual,
        basePosition=tuple(position),
    )
    p.changeDynamics(obj_id, -1, lateralFriction=0.8, spinningFriction=0.02, rollingFriction=0.02)
    return obj_id


def _split_commands(commands: str) -> list[str]:
    return [part.strip() for part in commands.replace("；", ";").split(";") if part.strip()]


def _is_pick_and_place_command(text: str) -> bool:
    has_pick = any(word in text for word in ["pick", "grasp", "抓取", "抓住", "拿起"])
    has_place = any(word in text for word in ["place", "放到", "放置"])
    return has_pick and has_place


def _parse_xyz(value: str) -> np.ndarray:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError("坐标必须是 x,y,z")
    return np.array(parts, dtype=float)


def _parse_xyz_from_command(command: str) -> np.ndarray:
    parts = command.replace(",", " ").split()[1:]
    if len(parts) != 3:
        raise ValueError("命令格式应为：move x y z 或 delta dx dy dz")
    return np.array([float(part) for part in parts], dtype=float)


def _parse_place_target(text: str, object_pos: np.ndarray) -> np.ndarray:
    target = np.array(object_pos, dtype=float)
    if any(word in text for word in ["left", "左"]):
        target[1] += 0.18
    elif any(word in text for word in ["right", "右"]):
        target[1] -= 0.18
    elif any(word in text for word in ["front", "前"]):
        target[0] += 0.18
    elif any(word in text for word in ["back", "后"]):
        target[0] -= 0.18
    else:
        parts = text.replace(",", " ").split()
        nums = []
        for part in parts:
            try:
                nums.append(float(part))
            except ValueError:
                pass
        if len(nums) == 3:
            target = np.array(nums, dtype=float)
        else:
            raise ValueError("放置命令格式：place left/right/front/back，或 place x y z")
    return target


def _is_direction_command(text: str) -> bool:
    direction_words = [
        "up",
        "down",
        "left",
        "right",
        "front",
        "back",
        "向上",
        "向下",
        "向左",
        "向右",
        "向前",
        "向后",
        "上移",
        "下移",
        "左移",
        "右移",
        "前移",
        "后移",
    ]
    return any(word in text for word in direction_words)


def _parse_direction_delta(text: str) -> np.ndarray:
    distance = _first_number(text, default=0.10)
    delta = np.zeros(3, dtype=float)
    if any(word in text for word in ["up", "向上", "上移"]):
        delta[2] += distance
    elif any(word in text for word in ["down", "向下", "下移"]):
        delta[2] -= distance
    elif any(word in text for word in ["left", "向左", "左移"]):
        delta[1] += distance
    elif any(word in text for word in ["right", "向右", "右移"]):
        delta[1] -= distance
    elif any(word in text for word in ["front", "向前", "前移"]):
        delta[0] += distance
    elif any(word in text for word in ["back", "向后", "后移"]):
        delta[0] -= distance
    else:
        raise ValueError("无法识别移动方向")
    return delta


def _first_number(text: str, default: float) -> float:
    cleaned = text.replace(",", " ")
    number = ""
    for char in cleaned:
        if char.isdigit() or char in ".-":
            number += char
        elif number:
            try:
                return abs(float(number))
            except ValueError:
                number = ""
    if number:
        try:
            return abs(float(number))
        except ValueError:
            pass
    return default


def _fmt_vec(value: np.ndarray) -> str:
    return "[" + ", ".join(f"{float(item):.3f}" for item in value) + "]"


if __name__ == "__main__":
    main()
