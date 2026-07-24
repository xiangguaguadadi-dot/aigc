"""Headless end-to-end verification for the live Blender add-on."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


def main():
    args = _parse_args()
    project_root = Path(__file__).resolve().parent.parent.parent
    addon_parent = project_root / "simulation" / "blender_addon"
    sys.path.insert(0, str(addon_parent))
    import robot_interaction as addon

    addon.register()
    scene = bpy.context.scene
    scene.robot_live_add_workbench = True
    addon.connect_to_server(args.host, args.port)

    hello = _pump_until(addon, scene, lambda message: message.get("type") == "hello", args.timeout)
    if len(addon._runtime.link_poses) != 11:
        raise AssertionError(f"Expected 11 live robot visuals, got {len(addon._runtime.link_poses)}")

    bpy.ops.robot_live.record(mode="start")
    request_id = "blender-verify-pick"
    addon._client.send({"type": "action", "id": request_id, "action": "pick"})
    pick_result = _wait_result(addon, scene, request_id, args.timeout)
    recorded_after_pick = addon._runtime.record_count
    if pick_result.get("status") != "completed" or recorded_after_pick < 5:
        raise AssertionError(f"Pick/record verification failed: {pick_result}, frames={recorded_after_pick}")
    if len(addon._runtime.contact_arrows) != 2:
        raise AssertionError("Expected two contact force arrows")
    if not scene.robot_live_contact_valid:
        raise AssertionError("Pick completed without Blender receiving valid force closure")
    contact_forces = [scene.robot_live_left_force, scene.robot_live_right_force]
    if any(force < 1.0 for force in contact_forces):
        raise AssertionError(f"Contact forces were not visualized: {contact_forces}")
    if any(arrow.hide_viewport for arrow in addon._runtime.contact_arrows):
        raise AssertionError("A contact force arrow is hidden after a valid pick")
    if addon._runtime.grasp_marker is None or scene.robot_live_grasp_score <= 0.0:
        raise AssertionError("Blender did not receive the planned 6D grasp pose")

    stop_id = "blender-verify-stop"
    addon._client.send({"type": "action", "id": stop_id, "action": "home"})
    state_count = 0
    stop_sent = False
    deadline = time.monotonic() + args.timeout
    stop_result = None
    while time.monotonic() < deadline:
        message = addon._client.incoming.get(timeout=1.0)
        addon._handle_message(scene, message)
        if message.get("type") == "state":
            state_count += 1
            if state_count >= 3 and not stop_sent:
                addon._client.send({"type": "stop"})
                stop_sent = True
        if (
            message.get("type") == "result"
            and message.get("id") == stop_id
            and message.get("status") in {"completed", "cancelled", "failed"}
        ):
            stop_result = message
            break
    if not stop_result or stop_result.get("status") != "cancelled":
        raise AssertionError(f"Stop verification failed: {stop_result}")

    bpy.ops.robot_live.create_target()
    target_marker = bpy.data.objects[addon.TARGET_NAME]
    target_local = Vector((0.48, 0.08, 0.88))
    target_marker.location = addon._runtime.root.matrix_world @ target_local
    scene.robot_live_target_operation = "move_to"
    bpy.ops.robot_live.target_action(action="check_feasibility")
    accepted = _pump_until(addon, scene, lambda message: message.get("type") == "accepted", args.timeout)
    feasibility_result = _wait_result(addon, scene, accepted["id"], args.timeout)
    if not feasibility_result.get("details", {}).get("feasible"):
        raise AssertionError(f"Target feasibility verification failed: {feasibility_result}")
    bpy.ops.robot_live.target_action(action="move_to")
    accepted = _pump_until(addon, scene, lambda message: message.get("type") == "accepted", args.timeout)
    target_result = _wait_result(addon, scene, accepted["id"], args.timeout)
    if target_result.get("status") != "completed":
        raise AssertionError(f"Target marker verification failed: {target_result}")

    target_marker.rotation_mode = "QUATERNION"
    target_marker.rotation_quaternion = Quaternion((0.9238795, 0.0, 0.0, 0.3826834))
    bpy.ops.robot_live.target_action(action="rotate_to")
    accepted = _pump_until(addon, scene, lambda message: message.get("type") == "accepted", args.timeout)
    rotate_result = _wait_result(addon, scene, accepted["id"], args.timeout)
    if rotate_result.get("status") != "completed":
        raise AssertionError(f"Target rotation verification failed: {rotate_result}")

    place_local = Vector((0.50, 0.14, 0.626))
    target_marker.location = addon._runtime.root.matrix_world @ place_local
    bpy.ops.robot_live.target_action(action="place_at")
    accepted = _pump_until(addon, scene, lambda message: message.get("type") == "accepted", args.timeout)
    place_result = _wait_result(addon, scene, accepted["id"], args.timeout)
    if place_result.get("status") != "completed":
        raise AssertionError(f"Target placement verification failed: {place_result}")
    if place_result.get("details", {}).get("operation") != "place_at":
        raise AssertionError(f"Placement returned incorrect action details: {place_result}")

    push_local = Vector((0.62, 0.14, 0.626))
    target_marker.location = addon._runtime.root.matrix_world @ push_local
    bpy.ops.robot_live.target_action(action="push_to")
    accepted = _pump_until(addon, scene, lambda message: message.get("type") == "accepted", args.timeout)
    push_result = _wait_result(addon, scene, accepted["id"], args.timeout)
    if push_result.get("status") != "completed":
        raise AssertionError(f"Target push verification failed: {push_result}")
    if push_result.get("details", {}).get("metrics", {}).get("target_error_m", 1.0) > 0.06:
        raise AssertionError(f"Target push stopped outside tolerance: {push_result}")

    reset_id = "blender-verify-reset"
    addon._client.send({"type": "action", "id": reset_id, "action": "reset_scene"})
    reset_result = _wait_result(addon, scene, reset_id, args.timeout)
    bpy.ops.robot_live.record(mode="stop")
    if reset_result.get("status") != "completed":
        raise AssertionError(f"Reset verification failed: {reset_result}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    blend_path = output_dir / "live_interaction_smoke.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    object_position = list(addon._runtime.object_pose.location)
    report = {
        "protocol_version": hello["protocol_version"],
        "robot_visuals": len(addon._runtime.link_poses),
        "last_sequence": addon._runtime.last_sequence,
        "recorded_states": addon._runtime.record_count,
        "pick_status": pick_result["status"],
        "pick_contact_forces_n": contact_forces,
        "contact_arrows": len(addon._runtime.contact_arrows),
        "grasp_planner": scene.robot_live_grasp_planner,
        "grasp_score": scene.robot_live_grasp_score,
        "stop_status": stop_result["status"],
        "target_status": target_result["status"],
        "feasibility_status": feasibility_result["details"]["feasible"],
        "rotate_status": rotate_result["status"],
        "place_status": place_result["status"],
        "push_status": push_result["status"],
        "push_metrics": push_result.get("details", {}).get("metrics", {}),
        "reset_status": reset_result["status"],
        "object_position_after_reset": object_position,
        "blend": str(blend_path),
    }
    report_path = output_dir / "live_interaction_report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    addon._client.disconnect(notify=False)
    print(f"LIVE_INTERACTION_REPORT={report_path}")


def _pump_until(addon, scene, predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            message = addon._client.incoming.get(timeout=1.0)
        except queue.Empty:
            continue
        addon._handle_message(scene, message)
        if predicate(message):
            return message
    raise TimeoutError("Timed out waiting for Blender live event")


def _wait_result(addon, scene, request_id, timeout):
    return _pump_until(
        addon,
        scene,
        lambda message: (
            message.get("type") == "result"
            and message.get("id") == request_id
            and message.get("status") in {"completed", "cancelled", "failed"}
        ),
        timeout,
    )


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output-dir", default="outputs/live_interaction_test")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
