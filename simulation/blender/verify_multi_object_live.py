"""Blender-side acceptance test for prepared multi-object interaction scenes."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector


def main():
    args = _parse_args()
    project_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(project_root / "simulation" / "blender_addon"))
    import robot_interaction as addon

    addon.register()
    scene = bpy.context.scene
    scene.robot_live_add_workbench = True
    addon.connect_to_server(args.host, args.port)
    hello = _pump_until(addon, scene, lambda message: message.get("type") == "hello", args.timeout)
    _pump_until(addon, scene, lambda message: message.get("type") == "state", args.timeout)

    objects = hello["scene"].get("objects", [])
    if len(objects) < 2 or len(addon._runtime.object_poses) < 2:
        raise AssertionError(f"Expected at least two independent objects: {objects}")
    chair_id = next(item["id"] for item in objects if item.get("dynamic"))
    static_id = next(item["id"] for item in objects if not item.get("dynamic"))
    static_start = addon._runtime.object_poses[static_id].location.copy()

    _select_active(addon, scene, static_id, args.timeout)
    bpy.ops.robot_live.create_target()
    target = bpy.data.objects[addon.TARGET_NAME]
    static_position = addon._runtime.object_poses[static_id].location.copy()
    target.location = addon._runtime.root.matrix_world @ Vector(
        (static_position.x + 0.10, static_position.y, 0.0)
    )
    scene.robot_live_target_operation = "push_to"
    static_check = _target_result(addon, scene, "check_feasibility", args.timeout)
    details = static_check.get("details", {})
    if details.get("feasible") or not any("static" in reason for reason in details.get("reasons", [])):
        raise AssertionError(f"Static object push was not rejected: {static_check}")

    _select_active(addon, scene, chair_id, args.timeout)
    chair_start = addon._runtime.object_poses[chair_id].location.copy()
    target.location = addon._runtime.root.matrix_world @ Vector(
        (chair_start.x + 0.10, chair_start.y, 0.0)
    )
    chair_check = _target_result(addon, scene, "check_feasibility", args.timeout)
    if not chair_check.get("details", {}).get("feasible"):
        raise AssertionError(f"Dynamic chair push was rejected: {chair_check}")
    push_result = _target_result(addon, scene, "push_to", args.timeout)
    if push_result.get("status") != "completed":
        raise AssertionError(f"Dynamic chair push failed: {push_result}")

    chair_end = addon._runtime.object_poses[chair_id].location.copy()
    static_end = addon._runtime.object_poses[static_id].location.copy()
    chair_distance = float((chair_end - chair_start).length)
    static_distance = float((static_end - static_start).length)
    if chair_distance < 0.04:
        raise AssertionError(f"Chair moved only {chair_distance:.3f} m")
    if static_distance > 0.002:
        raise AssertionError(f"Static object moved {static_distance:.4f} m")

    target.location = addon._runtime.root.matrix_world @ Vector(
        (chair_end.x, chair_end.y, max(0.40, chair_end.z))
    )
    move_result = _target_result(addon, scene, "move_to", args.timeout)
    if move_result.get("status") != "failed" or "contact" not in move_result.get("error", "").lower():
        raise AssertionError(f"Move EE collision path was not rejected: {move_result}")

    reset_result = _raw_action(addon, scene, "reset_scene", args.timeout)
    if reset_result.get("status") != "completed":
        raise AssertionError(f"Reset failed: {reset_result}")

    report = {
        "object_count": len(objects),
        "active_dynamic_object": chair_id,
        "static_object": static_id,
        "static_push_rejected": True,
        "chair_push_distance_m": chair_distance,
        "static_object_distance_m": static_distance,
        "move_ee_collision_rejected": True,
        "push_metrics": push_result.get("details", {}).get("metrics", {}),
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    addon._client.disconnect(notify=False)
    print(f"MULTI_OBJECT_LIVE_REPORT={output}")


def _select_active(addon, scene, object_id, timeout):
    scene.robot_live_active_object = object_id
    accepted = _pump_until(addon, scene, lambda message: message.get("type") == "accepted", timeout)
    result = _wait_result(addon, scene, accepted["id"], timeout)
    if result.get("status") != "completed":
        raise AssertionError(f"Could not select {object_id}: {result}")
    if scene.robot_live_active_object != object_id:
        raise AssertionError(f"Blender did not apply Active Object {object_id}")


def _target_result(addon, scene, action, timeout):
    bpy.ops.robot_live.target_action(action=action)
    accepted = _pump_until(addon, scene, lambda message: message.get("type") == "accepted", timeout)
    return _wait_result(addon, scene, accepted["id"], timeout)


def _raw_action(addon, scene, action, timeout):
    request_id = f"multi-{action}"
    addon._client.send({"type": "action", "id": request_id, "action": action})
    return _wait_result(addon, scene, request_id, timeout)


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
        lambda message: message.get("type") == "result"
        and message.get("id") == request_id
        and message.get("status") in {"completed", "failed", "cancelled"},
        timeout,
    )


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--output", default="outputs/multi_object_test/report.json")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
