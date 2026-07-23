"""
Interaction Primitives — Ray casting, Grasp, Push, Throw.

All operations work on an active PyBullet client.
"""

import numpy as np
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass


# ===========================================================================
# 1. Ray Casting
# ===========================================================================

def ray_cast(
    camera_pos: Tuple[float, float, float],
    camera_target: Tuple[float, float, float],
    body_ids: Optional[List[int]] = None,
    max_distance: float = 100.0,
) -> Optional[Dict]:
    """
    Shoot a ray from camera through target pixel, return first hit.

    Parameters
    ----------
    camera_pos : (3,)  camera world position
    camera_target : (3,)  point on image plane (in world)
    body_ids : list or None  restrict to these bodies (None = all)
    max_distance : float

    Returns
    -------
    dict or None  keys: body_id, hit_position, hit_normal, link_index, object_name
    """
    import pybullet as p

    ray_from = np.array(camera_pos, dtype=np.float64)
    ray_dir = np.array(camera_target, dtype=np.float64) - ray_from
    ray_dir = ray_dir / (np.linalg.norm(ray_dir) + 1e-10)

    if body_ids is None:
        body_ids = [
            i for i in range(p.getNumBodies())
            if p.getBodyInfo(i)[0].decode() != "ground"  # skip ground
        ]

    # Cast against each body
    best_hit = None
    best_dist = max_distance

    for body_id in body_ids:
        hit = p.rayTest(ray_from.tolist(), (ray_from + ray_dir * max_distance).tolist())
        for h in hit:
            if h[0] != body_id or h[2] < 0:
                continue
            dist = h[2]
            if dist < best_dist:
                best_dist = dist
                best_hit = {
                    "body_id": h[0],
                    "link_index": h[1],
                    "hit_fraction": float(h[2]),
                    "hit_position": list(h[3]),
                    "hit_normal": list(h[4]),
                    "object_name": p.getBodyInfo(body_id)[0].decode()
                                   if body_id >= 0 else "unknown",
                }

    return best_hit


def ray_cast_from_screen(
    screen_x: float,
    screen_y: float,
    screen_width: int = 640,
    screen_height: int = 480,
    camera_pos: Tuple[float, float, float] = (3, 2, 3),
    camera_target: Tuple[float, float, float] = (0, 0.5, 0),
    fov: float = 60.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert screen coordinates to world-space ray.

    Returns (ray_origin, ray_direction).
    """
    import pybullet as p

    proj = p.computeProjectionMatrixFOV(
        fov=fov, aspect=screen_width / screen_height,
        nearVal=0.1, farVal=100,
    )
    view = p.computeViewMatrix(
        cameraEyePosition=camera_pos,
        cameraTargetPosition=camera_target,
        cameraUpVector=[0, 1, 0],
    )

    # Compute ray in world space (simplified: use view-proj inverse)
    # For PyBullet, we approximate by sampling near/far plane
    eye = np.array(camera_pos)
    center = np.array(camera_target)
    forward = center - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, [0, 1, 0])
    right = right / np.linalg.norm(right)
    up = np.cross(right, forward)

    # Map screen to world ray direction
    aspect = screen_width / screen_height
    px = (2.0 * screen_x / screen_width - 1.0) * np.tan(np.radians(fov) / 2) * aspect
    py = (1.0 - 2.0 * screen_y / screen_height) * np.tan(np.radians(fov) / 2)

    ray_dir = forward + right * px + up * py
    ray_dir = ray_dir / np.linalg.norm(ray_dir)

    return eye, ray_dir


# ===========================================================================
# 2. Grasp Constraint
# ===========================================================================

@dataclass
class GraspState:
    """Tracks an active grasp."""
    body_id: int
    constraint_id: int
    grab_position: np.ndarray  # world position of grab point
    grab_offset: np.ndarray    # local offset in object frame


def grasp_object(
    body_id: int,
    grasp_position: Tuple[float, float, float],
    max_force: float = 500.0,
) -> int:
    """
    Create a point-to-point constraint simulating a grasp.

    The constraint pins the object at grasp_position to world.
    Returns constraint_id (used for drag/update and release).
    """
    import pybullet as p

    cid = p.createConstraint(
        parentBodyUniqueId=body_id,
        parentLinkIndex=-1,  # base link
        childBodyUniqueId=-1,  # world
        childLinkIndex=-1,
        jointType=p.JOINT_FIXED,
        jointAxis=[0, 0, 0],
        parentFramePosition=[0, 0, 0],  # at object COM (relative to parent)
        childFramePosition=list(grasp_position),  # world anchor point
    )

    # Override with max force
    p.changeConstraint(cid, maxForce=max_force)

    return cid


def update_grasp_position(
    constraint_id: int,
    new_world_position: Tuple[float, float, float],
):
    """Move grasped object to a new world position."""
    import pybullet as p

    p.changeConstraint(
        constraint_id,
        jointChildPivot=list(new_world_position),
        maxForce=500.0,
    )


def release_grasp(
    constraint_id: int,
    transfer_velocity: bool = True,
    body_id: Optional[int] = None,
):
    """
    Release grasp constraint.

    If transfer_velocity: apply the constraint body's current linear
    velocity as an impulse, so the object "flies" when thrown.
    """
    import pybullet as p

    if transfer_velocity and body_id is not None:
        # Get current velocity and apply as impulse
        vel, ang_vel = p.getBaseVelocity(body_id)
        # Apply additional impulse in direction of velocity
        if np.linalg.norm(vel) > 0.01:
            p.applyExternalForce(body_id, -1, vel, [0, 0, 0], p.WORLD_FRAME)

    p.removeConstraint(constraint_id)


# ===========================================================================
# 3. Push / Impulse
# ===========================================================================

def apply_push(
    body_id: int,
    force: Tuple[float, float, float],
    position: Optional[Tuple[float, float, float]] = None,
):
    """
    Apply an impulse force to an object.

    Parameters
    ----------
    body_id : int
    force : (3,)  impulse vector (N·s)
    position : (3,) or None  world position where force is applied
                             (None = at COM, produces no rotation)
    """
    import pybullet as p

    if position is None:
        # applyExternalForce with WORLD_FRAME acts as impulse over one step
        p.applyExternalForce(body_id, -1, list(force), [0, 0, 0], p.WORLD_FRAME)
    else:
        p.applyExternalForce(
            body_id, -1,
            forceObj=list(force),
            posObj=list(position),
            flags=p.WORLD_FRAME,
        )


def apply_torque(
    body_id: int,
    torque: Tuple[float, float, float],
):
    """Apply a torque impulse."""
    import pybullet as p
    p.applyExternalTorque(body_id, -1, list(torque), flags=p.WORLD_FRAME)


# ===========================================================================
# 4. Throw
# ===========================================================================

def throw_object(
    body_id: int,
    direction: Tuple[float, float, float],
    speed: float = 5.0,
):
    """
    Throw an object by setting its linear velocity.

    Parameters
    ----------
    body_id : int
    direction : (3,)  unit vector throw direction
    speed : float  m/s
    """
    import pybullet as p

    vel = np.array(direction, dtype=np.float64)
    vel = vel / (np.linalg.norm(vel) + 1e-10) * speed
    p.resetBaseVelocity(body_id, linearVelocity=vel.tolist())


# ===========================================================================
# 5. State Sync
# ===========================================================================

def sync_object_transforms(
    body_ids: List[int],
) -> Dict[int, Dict]:
    """
    Read current physics state: position, orientation, velocity for all bodies.

    Returns dict: body_id → {position, orientation, linear_vel, angular_vel}
    """
    import pybullet as p

    states = {}
    for bid in body_ids:
        pos, orn = p.getBasePositionAndOrientation(bid)
        vel, ang = p.getBaseVelocity(bid)
        name = p.getBodyInfo(bid)[0].decode() if bid >= 0 else "unknown"
        states[bid] = {
            "name": name,
            "position": list(pos),
            "orientation": list(orn),
            "linear_velocity": list(vel),
            "angular_velocity": list(ang),
        }
    return states
