"""Franka Panda robot controller for PyBullet."""

import pybullet as p
import pybullet_data
import numpy as np
from pathlib import Path


class PandaRobot:
    """Controls the Franka Panda robot arm in PyBullet.

    Provides: joint control, inverse kinematics, gripper control.
    """

    def __init__(self, base_position: list = [0, 0, 0]):
        self.base_position = base_position
        self.body_id = None
        self._joint_indices = {}
        self._finger_joints = []
        self._num_joints = 0
        self.arm_force = 500.0
        self.position_gain = 0.18
        self.velocity_gain = 0.8
        self.arm_joint_names = [
            "panda_joint1",
            "panda_joint2",
            "panda_joint3",
            "panda_joint4",
            "panda_joint5",
            "panda_joint6",
            "panda_joint7",
        ]
        self.arm_torque_limits = np.array([87.0, 87.0, 87.0, 87.0, 12.0, 12.0, 12.0])
        self.last_arm_torques = np.zeros(7, dtype=float)
        self.arm_joint_indices = []
        self.movable_joint_indices = []
        self._dof_position = {}
        self.ik_lower_limits = []
        self.ik_upper_limits = []
        self.ik_joint_ranges = []
        self.home_pose = {
            "panda_joint1": 0.0,
            "panda_joint2": -0.8,
            "panda_joint3": 0.0,
            "panda_joint4": -2.1,
            "panda_joint5": 0.0,
            "panda_joint6": 1.6,
            "panda_joint7": 0.8,
        }

    def load(self):
        """Load the Panda URDF into PyBullet."""
        self.body_id = p.loadURDF(
            "franka_panda/panda.urdf",
            self.base_position, [0, 0, 0, 1],
            useFixedBase=True,  # robot arm is fixed to the ground
        )

        # Parse joint info
        self._joint_indices = {}
        self._finger_joints = []

        for i in range(p.getNumJoints(self.body_id)):
            info = p.getJointInfo(self.body_id, i)
            joint_name = info[1].decode("utf-8")
            joint_type = info[2]  # JOINT_REVOLUTE, JOINT_PRISMATIC, etc.

            self._joint_indices[joint_name] = i

            # Identify gripper fingers
            if "finger" in joint_name.lower():
                self._finger_joints.append(i)

            if joint_type != p.JOINT_FIXED:
                self._dof_position[i] = len(self.movable_joint_indices)
                self.movable_joint_indices.append(i)

        self._num_joints = p.getNumJoints(self.body_id)
        self.arm_joint_indices = [self._joint_indices[name] for name in self.arm_joint_names]
        for joint_index in self.movable_joint_indices:
            info = p.getJointInfo(self.body_id, joint_index)
            lower = float(info[8])
            upper = float(info[9])
            if lower >= upper:
                lower, upper = -np.pi, np.pi
            self.ik_lower_limits.append(lower)
            self.ik_upper_limits.append(upper)
            self.ik_joint_ranges.append(upper - lower)

        # Force initial joint positions (resetJointState bypasses gravity)
        # Home pose: arm upright, reaching toward the table
        init_pose = self.home_pose

        # Reset each joint to its target position (instant, no physics)
        for name, angle in init_pose.items():
            if name in self._joint_indices:
                idx = self._joint_indices[name]
                p.resetJointState(self.body_id, idx, targetValue=angle)

        # Enable position control with high max force for all joints
        for name, idx in self._joint_indices.items():
            if "finger" not in name.lower():
                p.setJointMotorControl2(
                    self.body_id, idx,
                    p.POSITION_CONTROL,
                    targetPosition=init_pose.get(name, 0.0),
                    force=self.arm_force,
                    positionGain=self.position_gain,
                    velocityGain=self.velocity_gain,
                )

        # Gripper: open
        self.open_gripper()

        for finger_link in self._finger_joints:
            p.changeDynamics(
                self.body_id,
                finger_link,
                lateralFriction=1.4,
                spinningFriction=0.04,
                rollingFriction=0.01,
                restitution=0.0,
            )

        return self.body_id

    @property
    def hand_link_index(self) -> int:
        """Return the link index used as the Cartesian control frame."""
        return self._joint_indices.get("panda_hand_joint", self._num_joints - 1)

    @property
    def grasp_link_index(self) -> int:
        """Return the URDF grasp target located between the two fingers."""
        return self._joint_indices.get("panda_grasptarget_hand", self.hand_link_index)

    def reset_home(self):
        """Reset arm and gripper to the configured home pose."""
        for name, angle in self.home_pose.items():
            if name in self._joint_indices:
                p.resetJointState(self.body_id, self._joint_indices[name], angle)
        self.set_joint_positions(self.home_pose)
        self.open_gripper()

    def set_joint_positions(self, joint_pose: dict):
        """Set joint target positions using position control.

        Args:
            joint_pose: {joint_name: target_angle}
        """
        for name, angle in joint_pose.items():
            if name in self._joint_indices:
                idx = self._joint_indices[name]
                p.setJointMotorControl2(
                    self.body_id, idx,
                    p.POSITION_CONTROL,
                    targetPosition=angle,
                    force=self.arm_force,
                    positionGain=self.position_gain,
                    velocityGain=self.velocity_gain,
                )

    def get_joint_positions(self) -> dict:
        """Get current joint angles."""
        state = {}
        for name, idx in self._joint_indices.items():
            joint_state = p.getJointState(self.body_id, idx)
            state[name] = joint_state[0]
        return state

    def get_end_effector_pose(self) -> tuple[np.ndarray, np.ndarray]:
        """Get [position, orientation] of the end-effector.

        Returns:
            position: (3,) array
            orientation: (4,) quaternion [x, y, z, w]
        """
        link_state = p.getLinkState(self.body_id, self.hand_link_index)
        return np.array(link_state[4]), np.array(link_state[5])

    def get_grasp_pose(self) -> tuple[np.ndarray, np.ndarray]:
        """Get the world pose of the grasp target between the gripper fingers."""
        link_state = p.getLinkState(self.body_id, self.grasp_link_index)
        return np.array(link_state[4]), np.array(link_state[5])

    def inverse_kinematics(
        self,
        target_pos: np.ndarray,
        target_orn: np.ndarray | None = None,
        link_index: int | None = None,
        rest_positions: np.ndarray | None = None,
    ) -> dict:
        """Compute IK to reach a target end-effector pose.

        Args:
            target_pos: (3,) target position in world coordinates
            target_orn: (4,) target orientation quaternion [x,y,z,w]

        Returns:
            dict of {joint_name: angle} for all 7 arm joints
        """
        ee_index = self.hand_link_index if link_index is None else int(link_index)

        current = np.asarray(
            [p.getJointState(self.body_id, index)[0] for index in self.movable_joint_indices],
            dtype=float,
        )
        if rest_positions is not None:
            requested_rest = np.asarray(rest_positions, dtype=float)
            if requested_rest.shape == (len(self.arm_joint_indices),):
                current[: len(self.arm_joint_indices)] = requested_rest
            elif requested_rest.shape == current.shape:
                current = requested_rest.copy()
            else:
                raise ValueError(
                    "IK rest_positions must contain the seven arm joints or all movable joints"
                )

        kwargs = {
            "lowerLimits": self.ik_lower_limits,
            "upperLimits": self.ik_upper_limits,
            "jointRanges": self.ik_joint_ranges,
            "restPoses": current.tolist(),
            "jointDamping": [0.01] * len(self.movable_joint_indices),
            "maxNumIterations": 240,
            "residualThreshold": 1e-5,
        }
        if target_orn is None:
            joint_angles = p.calculateInverseKinematics(
                self.body_id,
                ee_index,
                target_pos,
                **kwargs,
            )
        else:
            joint_angles = p.calculateInverseKinematics(
                self.body_id,
                ee_index,
                target_pos,
                target_orn,
                **kwargs,
            )

        # Map IK result to joint names (skip fixed joints)
        result = {}
        arm_joints = [j for j in range(7)]  # panda has 7 arm joints
        for i, idx in enumerate(arm_joints):
            if i < len(joint_angles):
                # Find the joint name for this index
                for name, jidx in self._joint_indices.items():
                    if jidx == idx and "finger" not in name.lower():
                        result[name] = joint_angles[i]
                        break

        return result

    def enable_torque_control(self):
        """Disable default arm motors so commanded forces control all seven joints."""
        self.last_arm_torques.fill(0.0)
        p.setJointMotorControlArray(
            self.body_id,
            self.arm_joint_indices,
            p.VELOCITY_CONTROL,
            targetVelocities=[0.0] * len(self.arm_joint_indices),
            forces=[0.0] * len(self.arm_joint_indices),
        )

    def get_arm_state(self) -> tuple[np.ndarray, np.ndarray]:
        states = p.getJointStates(self.body_id, self.arm_joint_indices)
        positions = np.array([state[0] for state in states], dtype=float)
        velocities = np.array([state[1] for state in states], dtype=float)
        return positions, velocities

    def apply_arm_torques(self, torques: np.ndarray):
        torques = np.clip(
            np.asarray(torques, dtype=float),
            -self.arm_torque_limits,
            self.arm_torque_limits,
        )
        self.last_arm_torques = torques.copy()
        p.setJointMotorControlArray(
            self.body_id,
            self.arm_joint_indices,
            p.TORQUE_CONTROL,
            forces=torques.tolist(),
        )

    def inverse_dynamics(self, arm_acceleration: np.ndarray) -> np.ndarray:
        """Compute arm torques while including the two finger DOFs in dynamics."""
        states = p.getJointStates(self.body_id, self.movable_joint_indices)
        positions = [float(state[0]) for state in states]
        velocities = [float(state[1]) for state in states]
        accelerations = [0.0] * len(self.movable_joint_indices)
        arm_acceleration = np.asarray(arm_acceleration, dtype=float)
        for arm_offset, joint_idx in enumerate(self.arm_joint_indices):
            accelerations[self._dof_position[joint_idx]] = float(arm_acceleration[arm_offset])
        torques = p.calculateInverseDynamics(
            self.body_id,
            positions,
            velocities,
            accelerations,
        )
        return np.array(
            [torques[self._dof_position[joint_idx]] for joint_idx in self.arm_joint_indices],
            dtype=float,
        )

    def linear_jacobian(self, link_index: int) -> np.ndarray:
        """Return the world linear Jacobian for a link, restricted to arm DOFs."""
        linear, _ = self.jacobian(link_index)
        return linear

    def jacobian(self, link_index: int) -> tuple[np.ndarray, np.ndarray]:
        """Return world linear/angular Jacobians restricted to the seven arm DOFs."""
        states = p.getJointStates(self.body_id, self.movable_joint_indices)
        positions = [float(state[0]) for state in states]
        zeros = [0.0] * len(self.movable_joint_indices)
        linear, angular = p.calculateJacobian(
            self.body_id,
            int(link_index),
            [0.0, 0.0, 0.0],
            positions,
            zeros,
            zeros,
        )
        linear = np.asarray(linear, dtype=float)
        angular = np.asarray(angular, dtype=float)
        columns = [self._dof_position[joint_idx] for joint_idx in self.arm_joint_indices]
        return linear[:, columns], angular[:, columns]

    def move_by_delta(
        self,
        delta: np.ndarray,
        target_orn: np.ndarray | None = None,
        workspace: tuple[np.ndarray, np.ndarray] | None = None,
        steps: int = 20,
        kinematic: bool = False,
    ):
        """Move the end-effector by a bounded Cartesian delta."""
        current_pos, _ = self.get_end_effector_pose()
        target_pos = current_pos + np.asarray(delta, dtype=float)
        if workspace is not None:
            low, high = workspace
            target_pos = np.clip(target_pos, low, high)
        self.move_to_pose(target_pos, target_orn, steps=steps, kinematic=kinematic)

    def get_gripper_opening(self) -> float:
        """Return approximate total distance between the two finger joints."""
        opening = 0.0
        for joint_idx in self._finger_joints:
            opening += float(p.getJointState(self.body_id, joint_idx)[0])
        return opening

    def move_to_pose(
        self,
        target_pos: np.ndarray,
        target_orn: np.ndarray | None = None,
        steps: int = 50,
        kinematic: bool = False,
    ):
        """Move the end-effector to a target position using IK.

        Args:
            target_pos: (3,) target position
            target_orn: (4,) target orientation quaternion
            steps: Number of simulation steps to take
        """
        joint_targets = self.inverse_kinematics(target_pos, target_orn)

        if kinematic:
            start = self.get_joint_positions()
            for step in range(1, steps + 1):
                alpha = step / max(1, steps)
                for name in self.arm_joint_names:
                    if name not in joint_targets or name not in self._joint_indices:
                        continue
                    value = (1.0 - alpha) * start.get(name, 0.0) + alpha * joint_targets[name]
                    p.resetJointState(self.body_id, self._joint_indices[name], value)
                p.stepSimulation()
            self.set_joint_positions(joint_targets)
            return

        for _ in range(steps):
            self.set_joint_positions(joint_targets)
            p.stepSimulation()

    def open_gripper(self):
        """Open the gripper fingers."""
        for joint_idx in self._finger_joints:
            p.setJointMotorControl2(
                self.body_id, joint_idx,
                p.POSITION_CONTROL,
                targetPosition=0.04,  # open width
                force=10.0,
            )

    def close_gripper(self, force: float = 15.0):
        """Close the gripper fingers."""
        for joint_idx in self._finger_joints:
            p.setJointMotorControl2(
                self.body_id, joint_idx,
                p.POSITION_CONTROL,
                targetPosition=0.0,  # closed
                force=float(force),
            )

    def grasp(self, target_pos: np.ndarray, above_offset: float = 0.1):
        """Execute a full grasp sequence: approach → close → lift.

        Args:
            target_pos: (3,) position of the object to grasp
            above_offset: Height above object for approach pose
        """
        # 1. Move above object
        target_pos = np.asarray(target_pos, dtype=float)
        above_pos = target_pos + np.array([0, 0, above_offset])
        print(f"  Moving above object: {above_pos.round(3)}")
        self.move_to_pose(above_pos, steps=80)

        # 2. Open gripper
        self.open_gripper()
        for _ in range(20):
            p.stepSimulation()

        # 3. Move down to object
        print(f"  Approaching object: {target_pos.round(3)}")
        self.move_to_pose(target_pos, steps=60)

        # 4. Close gripper
        print("  Closing gripper...")
        self.close_gripper()
        for _ in range(30):
            p.stepSimulation()

        # 5. Lift
        print("  Lifting...")
        self.move_to_pose(above_pos, steps=60)

        print("  Grasp complete!")

    def get_joint_info_summary(self):
        """Print all joint info for debugging."""
        print(f"Robot body ID: {self.body_id}")
        print(f"Number of joints: {self._num_joints}")
        for name, idx in sorted(self._joint_indices.items()):
            info = p.getJointInfo(self.body_id, idx)
            joint_type = ["REVOLUTE", "PRISMATIC", "SPHERICAL", "PLANAR", "FIXED"][info[2]]
            print(f"  [{idx}] {name}: type={joint_type}")
