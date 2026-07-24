"""Blender add-on for live PyBullet robot interaction."""

from __future__ import annotations

import json
import hashlib
import math
import os
import queue
import socket
import tempfile
import textwrap
import threading
import uuid
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from mathutils import Matrix, Quaternion, Vector


bl_info = {
    "name": "Robot Interaction",
    "author": "AIGC Project",
    "version": (1, 3, 0),
    "blender": (4, 3, 0),
    "location": "3D Viewport > Sidebar > Robot",
    "description": "Control a live PyBullet Panda robot inside Blender",
    "category": "3D View",
}

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024 * 1024
LIVE_COLLECTION = "Robot_Live"
LIVE_ROOT = "LIVE_Replay_World"
TARGET_NAME = "Robot_Target"
CONTACT_ARROW_NAMES = ("LIVE_Left_Contact_Force", "LIVE_Right_Contact_Force")


class _LiveClient:
    def __init__(self):
        self.socket = None
        self.reader = None
        self.thread = None
        self.stop_event = threading.Event()
        self.incoming = queue.Queue(maxsize=256)
        self.send_lock = threading.Lock()

    @property
    def connected(self):
        return self.socket is not None and not self.stop_event.is_set()

    def connect(self, host, port):
        self.disconnect(notify=False)
        while True:
            try:
                self.incoming.get_nowait()
            except queue.Empty:
                break
        self.stop_event.clear()
        connection = socket.create_connection((host, port), timeout=4.0)
        connection.settimeout(None)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket = connection
        self.reader = connection.makefile("rb")
        self.thread = threading.Thread(target=self._read_loop, name="blender-robot-live", daemon=True)
        self.thread.start()

    def disconnect(self, notify=True):
        self.stop_event.set()
        connection = self.socket
        self.socket = None
        reader = self.reader
        self.reader = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        if reader is not None:
            try:
                reader.close()
            except OSError:
                pass
        if notify:
            self._put({"type": "client_disconnected", "reason": "Disconnected"})

    def send(self, message):
        connection = self.socket
        if connection is None:
            raise ConnectionError("Not connected to the robot server")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with self.send_lock:
            connection.sendall(payload)

    def drain(self, limit=40):
        messages = []
        for _ in range(limit):
            try:
                messages.append(self.incoming.get_nowait())
            except queue.Empty:
                break
        return messages

    def _read_loop(self):
        reason = "Server disconnected"
        try:
            while not self.stop_event.is_set():
                line = self.reader.readline(MAX_MESSAGE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE_BYTES:
                    raise ValueError("Server message is too large")
                message = json.loads(line.decode("utf-8"))
                if isinstance(message, dict):
                    self._put(message)
        except Exception as exc:
            reason = str(exc)
        finally:
            was_active = not self.stop_event.is_set()
            self.stop_event.set()
            connection = self.socket
            self.socket = None
            reader = self.reader
            self.reader = None
            if reader is not None:
                try:
                    reader.close()
                except OSError:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            if was_active:
                self._put({"type": "client_disconnected", "reason": reason})

    def _put(self, message):
        try:
            self.incoming.put_nowait(message)
        except queue.Full:
            if message.get("type") == "state":
                return
            try:
                self.incoming.get_nowait()
            except queue.Empty:
                pass
            try:
                self.incoming.put_nowait(message)
            except queue.Full:
                pass


class _Runtime:
    def __init__(self):
        self.manifest = None
        self.root = None
        self.link_poses = {}
        self.object_poses = {}
        self.object_pose = None
        self.grasp_marker = None
        self.contact_arrows = []
        self.last_sequence = -1
        self.recording = False
        self.record_start_frame = 1
        self.record_count = 0
        self.record_adjust_end = False
        self.recorded_frames = []
        self.syncing_active_object = False

    def clear(self):
        self.manifest = None
        self.root = None
        self.link_poses = {}
        self.object_poses = {}
        self.object_pose = None
        self.grasp_marker = None
        self.contact_arrows = []
        self.last_sequence = -1
        self.recording = False
        self.record_count = 0
        self.record_adjust_end = False
        self.recorded_frames = []
        self.syncing_active_object = False


_client = _LiveClient()
_runtime = _Runtime()
_addon_active = False


def connect_to_server(host="127.0.0.1", port=8765):
    scene = bpy.context.scene
    if _runtime.recording:
        _finish_recording(scene)
    scene.robot_live_host = host
    scene.robot_live_port = port
    scene.robot_live_status = "Connecting"
    _client.connect(host, port)


def _process_network_events():
    if not _addon_active:
        return None
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return 0.2
    for message in _client.drain():
        _handle_message(scene, message)
    return 0.03 if _client.connected else 0.2


def _handle_message(scene, message):
    message_type = message.get("type")
    if message_type == "hello":
        if message.get("protocol_version") != PROTOCOL_VERSION:
            scene.robot_live_status = "Protocol mismatch"
            _client.disconnect()
            return
        scene.robot_live_status = "Connected"
        scene.robot_live_last_result = "Scene received"
        scene.render.fps = int(message.get("stream_fps", 30))
        _build_live_scene(scene, message["scene"])
    elif message_type == "state":
        _apply_state(scene, message)
    elif message_type == "accepted":
        scene.robot_live_last_result = f"Queued: {message.get('id', '')}"
    elif message_type == "result":
        status = message.get("status", "unknown")
        details = message.get("details")
        if details and status != "started":
            scene.robot_live_target_status = details.get("summary", status)
            scene.robot_live_last_result = scene.robot_live_target_status
            _set_target_validity(bool(details.get("feasible")) and status != "failed")
            metrics = details.get("metrics", {})
            grasp = metrics.get("executed_grasp") or metrics.get("selected_grasp")
            if grasp:
                scene.robot_live_grasp_score = float(grasp.get("score", 0.0))
                scene.robot_live_grasp_planner = str(metrics.get("grasp_planner", "6D grasp"))
                _show_grasp_marker(grasp)
        else:
            scene.robot_live_last_result = status if not message.get("error") else f"{status}: {message['error']}"
        if status == "started":
            scene.robot_live_status = "Running"
        elif status in {"completed", "cancelled", "failed"}:
            scene.robot_live_status = "Connected"
    elif message_type == "stop_ack":
        scene.robot_live_last_result = f"Stop requested; cleared {message.get('cleared_commands', 0)} queued"
    elif message_type in {"error", "server_error"}:
        scene.robot_live_status = "Error"
        scene.robot_live_last_result = message.get("error", "Unknown server error")
    elif message_type == "client_disconnected":
        scene.robot_live_status = "Disconnected"
        scene.robot_live_last_result = message.get("reason", "Disconnected")
        if _runtime.recording:
            _finish_recording(scene)


def _build_live_scene(scene, manifest):
    _remove_live_collection()
    _runtime.clear()
    collection = bpy.data.collections.new(LIVE_COLLECTION)
    scene.collection.children.link(collection)
    root = _new_empty(LIVE_ROOT, collection)
    root["robot_live_owned"] = True
    _runtime.root = root
    _runtime.manifest = manifest
    _apply_calibration(scene)

    for shape in manifest["robot"]["visual_shapes"]:
        pose = _new_empty(f"LIVE_{shape['id']}", collection)
        pose.parent = root
        pose["robot_live_owned"] = True
        imported = []
        mesh_path = Path(shape["mesh_path"]) if shape.get("mesh_path") else None
        if mesh_path and mesh_path.exists() and mesh_path.suffix.lower() == ".obj":
            imported = _import_obj(mesh_path)
        if not imported:
            imported = [_fallback_robot_mesh(shape, collection)]
        for obj in imported:
            _move_to_collection(obj, collection)
            obj.parent = pose
            obj["robot_live_owned"] = True
            _smooth_mesh(obj)
        _runtime.link_poses[shape["id"]] = pose

    object_infos = manifest.get("objects") or [manifest["object"]]
    for object_info in object_infos:
        object_id = str(object_info.get("id", "object"))
        _runtime.object_poses[object_id] = _build_live_object(
            scene,
            object_info,
            collection,
            root,
            object_id,
            allow_bound=(object_id == manifest.get("active_object_id", "object")),
        )
    active_object_id = str(manifest.get("active_object_id", object_infos[0].get("id", "object")))
    _runtime.object_pose = _runtime.object_poses.get(active_object_id)
    _runtime.syncing_active_object = True
    try:
        scene.robot_live_active_object = active_object_id
    finally:
        _runtime.syncing_active_object = False
    _runtime.contact_arrows = _build_contact_arrows(collection, root)
    if scene.robot_live_add_workbench:
        _build_workbench(collection, root, manifest.get("table", {}).get("enabled", True))
    scene.robot_live_last_result = (
        f"Loaded {len(_runtime.link_poses)} robot visuals / "
        f"{len(_runtime.object_poses)} scene objects"
    )


def _build_live_object(scene, object_info, collection, root, object_id="object", allow_bound=True):
    pose = _new_empty(f"LIVE_Object_{object_id}", collection)
    pose.parent = root
    pose["robot_live_owned"] = True
    initial_position = object_info.get("initial_position", [0.5, 0.0, 0.66])
    pose.location = initial_position

    bound = (
        bpy.data.objects.get(scene.robot_live_object_name)
        if allow_bound and scene.robot_live_object_name
        else None
    )
    if bound is not None and bound != pose:
        world_matrix = bound.matrix_world.copy()
        bound.parent = pose
        bound.matrix_parent_inverse = Matrix.Identity(4)
        bound.matrix_basis = pose.matrix_world.inverted() @ world_matrix
        bound["robot_live_bound_object"] = True
        return pose

    imported = []
    source = object_info.get("source_path")
    if source and Path(source).exists():
        imported = _import_asset(Path(source))
    if imported:
        for obj in imported:
            _move_to_collection(obj, collection)
            if obj.parent is None:
                obj.parent = pose
            obj["robot_live_owned"] = True
        scale = float(object_info.get("scale", 1.0))
        pose.scale = (scale, scale, scale)
    else:
        size = object_info.get("fallback_size", [0.05, 0.05, 0.05])
        cube = _create_box("LIVE_Demo_Object", size, (0, 0, 0), collection, (0.72, 0.03, 0.02, 1.0))
        cube.parent = pose
    return pose


def _apply_state(scene, message):
    sequence = int(message.get("sequence", -1))
    if sequence <= _runtime.last_sequence or _runtime.root is None:
        return
    _runtime.last_sequence = sequence
    for shape_id, transform in message.get("robot_links", {}).items():
        pose = _runtime.link_poses.get(shape_id)
        if pose is not None:
            _set_pose(pose, transform)
    object_states = message.get("objects") or {}
    if object_states:
        for object_id, transform in object_states.items():
            pose = _runtime.object_poses.get(object_id)
            if pose is not None:
                _set_pose(pose, transform)
    elif _runtime.object_pose is not None and message.get("object"):
        _set_pose(_runtime.object_pose, message["object"])
    active_object_id = message.get("active_object_id")
    if active_object_id in _runtime.object_poses:
        _runtime.object_pose = _runtime.object_poses[active_object_id]
        if scene.robot_live_active_object != active_object_id:
            _runtime.syncing_active_object = True
            try:
                scene.robot_live_active_object = active_object_id
            finally:
                _runtime.syncing_active_object = False

    command = message.get("command")
    if command:
        scene.robot_live_last_result = f"{command.get('label', 'command')}: {command.get('status', 'running')}"
    scene.robot_live_grasped = bool(message.get("grasped"))
    _apply_grasp_contacts(scene, message.get("grasp_contacts"))
    scene.robot_live_sequence = sequence
    if _runtime.recording:
        _record_current_state(scene)
    _tag_viewports()


def _build_contact_arrows(collection, root):
    arrows = []
    colors = ((0.05, 0.55, 1.0, 1.0), (1.0, 0.45, 0.03, 1.0))
    for name, color in zip(CONTACT_ARROW_NAMES, colors):
        arrow = _new_empty(name, collection)
        arrow.parent = root
        arrow["robot_live_owned"] = True
        arrow.empty_display_type = "SINGLE_ARROW"
        arrow.empty_display_size = 0.075
        arrow.color = color
        arrow.show_in_front = True
        arrow.hide_viewport = True
        arrow.hide_render = True
        arrows.append(arrow)
    return arrows


def _show_grasp_marker(grasp):
    if _runtime.root is None:
        return
    marker = _runtime.grasp_marker
    if marker is None:
        collection = bpy.data.collections.get(LIVE_COLLECTION)
        if collection is None:
            return
        marker = _new_empty("LIVE_Planned_Grasp", collection)
        marker.parent = _runtime.root
        marker["robot_live_owned"] = True
        marker.empty_display_type = "ARROWS"
        marker.empty_display_size = 0.085
        marker.show_in_front = True
        marker.color = (0.05, 0.75, 0.65, 1.0)
        _runtime.grasp_marker = marker
    _set_pose(
        marker,
        {
            "position": grasp["position"],
            "orientation": grasp["orientation"],
        },
    )
    marker.hide_viewport = False


def _apply_grasp_contacts(scene, summary):
    fingers = summary.get("fingers", []) if isinstance(summary, dict) else []
    forces = [0.0, 0.0]
    for index, arrow in enumerate(_runtime.contact_arrows):
        finger = fingers[index] if index < len(fingers) and isinstance(fingers[index], dict) else None
        force = max(0.0, float(finger.get("force", 0.0))) if finger else 0.0
        point = finger.get("point") if finger else None
        normal = Vector(finger.get("normal", (0.0, 0.0, 0.0))) if finger else Vector()
        forces[index] = force
        visible = force > 0.0 and point is not None and normal.length_squared > 1e-10
        arrow.hide_viewport = not visible
        arrow.hide_render = True
        if not visible:
            continue

        # PyBullet reports the normal on the object toward the finger. Its
        # negative is the force direction applied by the finger to the object.
        force_direction = -normal.normalized()
        arrow.location = tuple(point)
        arrow.rotation_mode = "QUATERNION"
        arrow.rotation_quaternion = force_direction.to_track_quat("Z", "Y")
        scale = min(2.0, max(0.25, force / 15.0))
        arrow.scale = (scale, scale, scale)

    scene.robot_live_left_force = forces[0]
    scene.robot_live_right_force = forces[1]
    scene.robot_live_contact_valid = bool(summary and summary.get("valid"))


def _set_pose(obj, transform):
    obj.location = tuple(transform["position"])
    quaternion = transform["orientation"]
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Quaternion((quaternion[3], quaternion[0], quaternion[1], quaternion[2]))


def _record_current_state(scene):
    frame = _runtime.record_start_frame + _runtime.record_count
    transforms = {}
    for shape_id, obj in _runtime.link_poses.items():
        transforms[shape_id] = (tuple(obj.location), tuple(obj.rotation_quaternion))
    for object_id, pose in _runtime.object_poses.items():
        transforms[f"__object__:{object_id}"] = (
            tuple(pose.location),
            tuple(pose.rotation_quaternion),
        )
    _runtime.recorded_frames.append((frame, transforms))
    _runtime.record_count += 1
    scene.robot_live_record_count = _runtime.record_count
    scene.frame_end = frame if _runtime.record_adjust_end else max(scene.frame_end, frame)


def _finish_recording(scene):
    _runtime.recording = False
    scene.robot_live_recording = False
    for frame, transforms in _runtime.recorded_frames:
        for shape_id, (location, rotation) in transforms.items():
            if shape_id.startswith("__object__:"):
                obj = _runtime.object_poses.get(shape_id.split(":", 1)[1])
            elif shape_id == "__object__":
                obj = _runtime.object_pose
            else:
                obj = _runtime.link_poses.get(shape_id)
            if obj is None:
                continue
            obj.location = location
            obj.rotation_mode = "QUATERNION"
            obj.rotation_quaternion = rotation
            obj.keyframe_insert(data_path="location", frame=frame, group="Live Robot")
            obj.keyframe_insert(data_path="rotation_quaternion", frame=frame, group="Live Robot")
    if _runtime.recorded_frames:
        scene.frame_set(_runtime.recorded_frames[-1][0])
    _set_recording_interpolation_linear()


def _set_recording_interpolation_linear():
    animated = list(_runtime.link_poses.values()) + list(_runtime.object_poses.values())
    for obj in animated:
        action = obj.animation_data.action if obj.animation_data and obj.animation_data.action else None
        if action is None:
            continue
        try:
            for curve in action.fcurves:
                for keyframe in curve.keyframe_points:
                    keyframe.interpolation = "LINEAR"
        except AttributeError:
            pass


def _apply_calibration(scene):
    root = _runtime.root or bpy.data.objects.get(LIVE_ROOT)
    if root is None:
        return
    root.location = scene.robot_live_offset
    scale = max(0.0001, scene.robot_live_scale)
    root.scale = (scale, scale, scale)
    root.rotation_mode = "XYZ"
    root.rotation_euler[2] = math.radians(scene.robot_live_rotation_z)


def _calibration_updated(self, context):
    _apply_calibration(context.scene)


def _active_object_items(self, context):
    manifest = _runtime.manifest or {}
    objects = manifest.get("objects") or ([manifest["object"]] if manifest.get("object") else [])
    if not objects:
        return [("NONE", "No scene objects", "Connect to a robot scene first")]
    return [
        (
            str(item.get("id", "object")),
            str(item.get("label", item.get("id", "object"))),
            "Dynamic" if item.get("dynamic", True) else "Static",
        )
        for item in objects
    ]


def _active_object_updated(self, context):
    if _runtime.syncing_active_object or not _client.connected:
        return
    object_id = context.scene.robot_live_active_object
    if object_id == "NONE" or object_id not in _runtime.object_poses:
        return
    _client.send(
        {
            "type": "action",
            "id": _request_id(),
            "action": "set_active_object",
            "object_id": object_id,
        }
    )


def _active_object_info():
    manifest = _runtime.manifest or {}
    active_id = getattr(bpy.context.scene, "robot_live_active_object", "")
    objects = manifest.get("objects") or ([manifest["object"]] if manifest.get("object") else [])
    return next((item for item in objects if str(item.get("id", "object")) == active_id), None)


class ROBOTLIVE_OT_connect(bpy.types.Operator):
    bl_idname = "robot_live.connect"
    bl_label = "Connect"
    bl_description = "Connect to the local PyBullet robot server"

    def execute(self, context):
        try:
            connect_to_server(context.scene.robot_live_host, context.scene.robot_live_port)
        except Exception as exc:
            context.scene.robot_live_status = "Error"
            context.scene.robot_live_last_result = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ROBOTLIVE_OT_disconnect(bpy.types.Operator):
    bl_idname = "robot_live.disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect from the robot server"

    def execute(self, context):
        _client.disconnect()
        context.scene.robot_live_status = "Disconnected"
        return {"FINISHED"}


class ROBOTLIVE_OT_send_command(bpy.types.Operator):
    bl_idname = "robot_live.send_command"
    bl_label = "Execute Command"
    bl_description = "Send the text command to PyBullet"

    def execute(self, context):
        text = context.scene.robot_live_command.strip()
        if not text:
            self.report({"ERROR"}, "Command is empty")
            return {"CANCELLED"}
        return _send_message(self, {"type": "command", "id": _request_id(), "text": text})


class ROBOTLIVE_OT_action(bpy.types.Operator):
    bl_idname = "robot_live.action"
    bl_label = "Robot Action"
    bl_description = "Run a predefined robot action"

    action: StringProperty()

    def execute(self, context):
        if self.action in {"place left", "place right", "place front", "place back"}:
            message = {"type": "command", "id": _request_id(), "text": self.action}
        else:
            message = {"type": "action", "id": _request_id(), "action": self.action}
        return _send_message(self, message)


class ROBOTLIVE_OT_stop(bpy.types.Operator):
    bl_idname = "robot_live.stop"
    bl_label = "Stop"
    bl_description = "Interrupt the current action and clear queued commands"

    def execute(self, context):
        return _send_message(self, {"type": "stop"})


class ROBOTLIVE_OT_create_target(bpy.types.Operator):
    bl_idname = "robot_live.create_target"
    bl_label = "Create Target"
    bl_description = "Create or select the target marker in the scene"

    def execute(self, context):
        marker = bpy.data.objects.get(TARGET_NAME)
        if marker is None:
            marker = bpy.data.objects.new(TARGET_NAME, None)
            context.scene.collection.objects.link(marker)
            marker.empty_display_type = "ARROWS"
            marker.empty_display_size = 0.10
            marker.show_in_front = True
            marker.color = (0.95, 0.16, 0.04, 1.0)
            object_info = _active_object_info() or (_runtime.manifest or {}).get("object", {})
            initial = object_info.get("initial_position", [0.5, 0.0, 0.66])
            table_info = (_runtime.manifest or {}).get("table", {})
            support_z = float(table_info.get("top_z", 0.626)) if table_info.get("enabled", True) else 0.0
            local_position = Vector((float(initial[0]), float(initial[1]) + 0.18, support_z))
            marker.location = (
                _runtime.root.matrix_world @ local_position if _runtime.root is not None else local_position
            )
            marker.rotation_mode = "QUATERNION"
            marker.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
        bpy.ops.object.select_all(action="DESELECT")
        marker.select_set(True)
        context.view_layer.objects.active = marker
        return {"FINISHED"}


class ROBOTLIVE_OT_target_action(bpy.types.Operator):
    bl_idname = "robot_live.target_action"
    bl_label = "Use Target"
    bl_description = "Execute or evaluate an operation using the complete Robot_Target pose"

    action: StringProperty(default="move_to")

    def execute(self, context):
        marker = bpy.data.objects.get(TARGET_NAME)
        if marker is None or _runtime.root is None:
            self.report({"ERROR"}, "Create a target and connect first")
            return {"CANCELLED"}
        local_matrix = _runtime.root.matrix_world.inverted() @ marker.matrix_world
        target = local_matrix.translation
        orientation = local_matrix.to_quaternion().normalized()
        action = self.action
        message = {
            "type": "action",
            "id": _request_id(),
            "action": action,
            "target": [float(value) for value in target],
            "orientation": [orientation.x, orientation.y, orientation.z, orientation.w],
        }
        if action == "check_feasibility":
            message["operation"] = context.scene.robot_live_target_operation
        return _send_message(
            self,
            message,
        )


class ROBOTLIVE_OT_snap_target(bpy.types.Operator):
    bl_idname = "robot_live.snap_target"
    bl_label = "Snap Target"
    bl_description = "Project Robot_Target onto the known table or floor support"

    def execute(self, context):
        marker = bpy.data.objects.get(TARGET_NAME)
        if marker is None or _runtime.root is None:
            self.report({"ERROR"}, "Create a target and connect first")
            return {"CANCELLED"}
        local_matrix = _runtime.root.matrix_world.inverted() @ marker.matrix_world
        local_position = local_matrix.translation
        table = (_runtime.manifest or {}).get("table", {})
        on_table = bool(table.get("enabled", True)) and (
            -0.25 <= local_position.x <= 1.25 and -0.5 <= local_position.y <= 0.5
        )
        local_position.z = float(table.get("top_z", 0.626)) if on_table else 0.0
        marker.location = _runtime.root.matrix_world @ local_position
        context.scene.robot_live_target_status = "Target snapped to table" if on_table else "Target snapped to floor"
        _set_target_validity(None)
        return {"FINISHED"}


def _set_target_validity(feasible):
    marker = bpy.data.objects.get(TARGET_NAME)
    if marker is None:
        return
    if feasible is True:
        marker.color = (0.06, 0.75, 0.22, 1.0)
    elif feasible is False:
        marker.color = (0.92, 0.05, 0.03, 1.0)
    else:
        marker.color = (0.95, 0.16, 0.04, 1.0)


class ROBOTLIVE_OT_bind_selected(bpy.types.Operator):
    bl_idname = "robot_live.bind_selected"
    bl_label = "Bind Selected Object"
    bl_description = "Use the selected environment object as the manipulated object on the next connection"

    def execute(self, context):
        if _client.connected:
            self.report({"ERROR"}, "Disconnect before changing the bound object")
            return {"CANCELLED"}
        selected = context.active_object
        if selected is None:
            self.report({"ERROR"}, "Select an object first")
            return {"CANCELLED"}
        context.scene.robot_live_object_name = selected.name
        return {"FINISHED"}


class ROBOTLIVE_OT_record(bpy.types.Operator):
    bl_idname = "robot_live.record"
    bl_label = "Live Recording"
    bl_description = "Start, stop, or clear live robot keyframes"

    mode: StringProperty(default="start")

    def execute(self, context):
        scene = context.scene
        if self.mode == "start":
            if _runtime.root is None:
                self.report({"ERROR"}, "Connect to the robot server first")
                return {"CANCELLED"}
            _runtime.recording = True
            _runtime.record_start_frame = scene.frame_current
            _runtime.record_count = 0
            _runtime.recorded_frames = []
            live_objects = set(_runtime.link_poses.values()) | set(_runtime.object_poses.values())
            _runtime.record_adjust_end = not any(
                obj.animation_data is not None and obj not in live_objects for obj in scene.objects
            )
            if _runtime.record_adjust_end:
                scene.frame_end = scene.frame_current
            scene.robot_live_recording = True
            scene.robot_live_record_count = 0
        elif self.mode == "stop":
            _finish_recording(scene)
        elif self.mode == "clear":
            _runtime.recording = False
            scene.robot_live_recording = False
            animated = list(_runtime.link_poses.values()) + list(_runtime.object_poses.values())
            for obj in animated:
                obj.animation_data_clear()
            _runtime.record_count = 0
            _runtime.record_adjust_end = False
            _runtime.recorded_frames = []
            scene.robot_live_record_count = 0
        return {"FINISHED"}


class ROBOTLIVE_PT_panel(bpy.types.Panel):
    bl_label = "Robot Interaction"
    bl_idname = "ROBOTLIVE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Robot"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        connected = _client.connected

        row = layout.row(align=True)
        row.label(text=scene.robot_live_status, icon="LINKED" if connected else "UNLINKED")
        row.label(text=f"Frame {scene.robot_live_sequence}")

        connection = layout.box()
        row = connection.row(align=True)
        row.prop(scene, "robot_live_host", text="")
        row.prop(scene, "robot_live_port", text="")
        row = connection.row(align=True)
        row.operator("robot_live.connect", icon="LINKED")
        row.operator("robot_live.disconnect", icon="UNLINKED")

        objects = layout.box()
        objects.label(text="Scene Objects")
        objects.prop(scene, "robot_live_active_object", text="Active")
        active_info = _active_object_info()
        if active_info:
            mode = "Dynamic" if active_info.get("dynamic", True) else "Static"
            properties = active_info.get("properties", {})
            mass = properties.get("mass_kg", {})
            objects.label(
                text=f"{mode} | mass confidence {float(mass.get('confidence', 1.0)):.2f}",
                icon="PHYSICS",
            )
        if scene.robot_live_grasp_planner:
            objects.label(
                text=f"{scene.robot_live_grasp_planner} | score {scene.robot_live_grasp_score:.3f}",
                icon="ORIENTATION_GIMBAL",
            )

        command = layout.box()
        command.prop(scene, "robot_live_command", text="")
        command.operator("robot_live.send_command", icon="PLAY")
        _draw_wrapped_label(command, scene.robot_live_last_result)

        actions = layout.box()
        grid = actions.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        _action_button(grid, "Pick", "pick", "VIEW_PAN")
        _action_button(grid, "Lift", "lift", "TRIA_UP")
        _action_button(grid, "Release", "release", "TRIA_DOWN")
        _action_button(grid, "Open", "open", "FULLSCREEN_ENTER")
        _action_button(grid, "Close", "close", "FULLSCREEN_EXIT")
        _action_button(grid, "Home", "home", "HOME")
        _action_button(grid, "Place L", "place left", "TRIA_LEFT")
        _action_button(grid, "Place R", "place right", "TRIA_RIGHT")
        _action_button(grid, "Reset", "reset_scene", "FILE_REFRESH")
        stop_row = actions.row()
        stop_row.alert = True
        stop_row.operator("robot_live.stop", icon="CANCEL")

        target = layout.box()
        target.label(text="Target Marker")
        row = target.row(align=True)
        row.operator("robot_live.create_target", icon="EMPTY_AXIS")
        row.operator("robot_live.snap_target", icon="SNAP_ON")
        target.prop(scene, "robot_live_target_operation", text="")
        operator = target.operator("robot_live.target_action", text="Check Feasibility", icon="CHECKMARK")
        operator.action = "check_feasibility"
        grid = target.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        operator = grid.operator("robot_live.target_action", text="Move EE", icon="CON_TRACKTO")
        operator.action = "move_to"
        operator = grid.operator("robot_live.target_action", text="Place", icon="IMPORT")
        operator.action = "place_at"
        operator = grid.operator("robot_live.target_action", text="Push", icon="FORWARD")
        operator.action = "push_to"
        operator = grid.operator("robot_live.target_action", text="Rotate", icon="DRIVER_ROTATIONAL_DIFFERENCE")
        operator.action = "rotate_to"
        if scene.robot_live_target_status:
            _draw_wrapped_label(target, scene.robot_live_target_status, icon="INFO")

        record = layout.box()
        row = record.row(align=True)
        if scene.robot_live_recording:
            operator = row.operator("robot_live.record", text="Stop Recording", icon="PAUSE")
            operator.mode = "stop"
        else:
            operator = row.operator("robot_live.record", text="Record", icon="REC")
            operator.mode = "start"
        operator = row.operator("robot_live.record", text="", icon="TRASH")
        operator.mode = "clear"
        record.label(text=f"Recorded states: {scene.robot_live_record_count}")

        calibration = layout.box()
        calibration.label(text="Replay Alignment")
        calibration.prop(scene, "robot_live_offset")
        calibration.prop(scene, "robot_live_scale")
        calibration.prop(scene, "robot_live_rotation_z")

        setup = layout.box()
        setup.prop(scene, "robot_live_add_workbench")
        setup.prop(scene, "robot_live_object_name")
        setup.operator("robot_live.bind_selected", icon="EYEDROPPER")
        setup.label(text=f"Grasped: {'Yes' if scene.robot_live_grasped else 'No'}")
        contact = setup.column(align=True)
        contact.label(
            text=f"Contact: {'Force closure' if scene.robot_live_contact_valid else 'Open'}",
            icon="CHECKMARK" if scene.robot_live_contact_valid else "X",
        )
        contact.label(text=f"Left finger: {scene.robot_live_left_force:.2f} N")
        contact.label(text=f"Right finger: {scene.robot_live_right_force:.2f} N")


class ROBOTLIVE_PT_item_panel(bpy.types.Panel):
    """Duplicate the controls in Blender's always-visible Item sidebar category."""

    bl_label = "Robot Interaction"
    bl_idname = "ROBOTLIVE_PT_item_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Item"
    bl_order = 0

    def draw(self, context):
        ROBOTLIVE_PT_panel.draw(self, context)


def _action_button(layout, text, action, icon):
    operator = layout.operator("robot_live.action", text=text, icon=icon)
    operator.action = action


def _draw_wrapped_label(layout, value, icon="NONE", width=46, max_lines=3):
    lines = textwrap.wrap(str(value), width=width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-3] + "..." if len(lines[-1]) >= 3 else "..."
    for index, line in enumerate(lines):
        layout.label(text=line, icon=icon if index == 0 else "NONE")


def _send_message(operator, message):
    try:
        _client.send(message)
    except Exception as exc:
        operator.report({"ERROR"}, str(exc))
        return {"CANCELLED"}
    return {"FINISHED"}


def _request_id():
    return f"blender-{uuid.uuid4().hex[:12]}"


def _new_empty(name, collection):
    obj = bpy.data.objects.new(name, None)
    collection.objects.link(obj)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0.04
    return obj


def _import_obj(path):
    path = _obj_without_missing_material(path)
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    return list(set(bpy.data.objects) - before)


def _obj_without_missing_material(path):
    """Cache OBJ files with broken mtllib lines removed to keep Blender logs clean."""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    except OSError:
        return path
    missing = []
    for line in lines:
        if line.lstrip().lower().startswith("mtllib "):
            material_name = line.strip().split(maxsplit=1)[1]
            if not (path.parent / material_name).exists():
                missing.append(material_name)
    if not missing:
        return path
    fingerprint = hashlib.sha256(f"{path.resolve()}|{path.stat().st_mtime_ns}".encode("utf-8")).hexdigest()[:12]
    cache_dir = Path(tempfile.gettempdir()) / "aigc_robot_live_meshes"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{path.stem}_{fingerprint}.obj"
    if not cached.exists():
        filtered = [
            line
            for line in lines
            if not (
                line.lstrip().lower().startswith("mtllib ")
                and line.strip().split(maxsplit=1)[1] in missing
            )
        ]
        temporary = cached.with_suffix(".obj.tmp")
        temporary.write_text("".join(filtered), encoding="utf-8")
        temporary.replace(cached)
    return cached


def _import_asset(path):
    before = set(bpy.data.objects)
    extension = path.suffix.lower()
    if extension in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif extension == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    elif extension == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        return []
    return list(set(bpy.data.objects) - before)


def _fallback_robot_mesh(shape, collection):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.045)
    obj = bpy.context.active_object
    obj.name = f"LIVE_Fallback_{shape['link_name']}"
    _move_to_collection(obj, collection)
    _assign_material(obj, "LIVE_Robot_White", (0.82, 0.86, 0.86, 1.0))
    return obj


def _build_workbench(collection, root, table_enabled=True):
    floor = _create_box("LIVE_Floor", (4.5, 4.5, 0.03), (0.35, 0, -0.015), collection, (0.09, 0.11, 0.12, 1))
    floor.parent = root
    if not table_enabled:
        return
    top = _create_box("LIVE_Workbench", (1.5, 1.0, 0.052), (0.5, 0, 0.6), collection, (0.7, 0.75, 0.74, 1))
    top.parent = root
    for index, (x, y) in enumerate(((-0.15, -0.4), (-0.15, 0.4), (1.15, -0.4), (1.15, 0.4))):
        leg = _create_box(f"LIVE_Leg_{index}", (0.1, 0.1, 0.58), (x, y, 0.29), collection, (0.04, 0.06, 0.07, 1))
        leg.parent = root


def _create_box(name, dimensions, location, collection, color):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _move_to_collection(obj, collection)
    obj["robot_live_owned"] = True
    _assign_material(obj, f"{name}_Material", color)
    return obj


def _assign_material(obj, name, color):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    if not obj.data.materials:
        obj.data.materials.append(material)


def _smooth_mesh(obj):
    if obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        if not obj.data.materials:
            _assign_material(obj, "LIVE_Robot_White", (0.82, 0.86, 0.86, 1.0))


def _move_to_collection(obj, collection):
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def _remove_live_collection():
    collection = bpy.data.collections.get(LIVE_COLLECTION)
    if collection is None:
        return
    for obj in list(collection.all_objects):
        if obj.get("robot_live_owned"):
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def _tag_viewports():
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


CLASSES = (
    ROBOTLIVE_OT_connect,
    ROBOTLIVE_OT_disconnect,
    ROBOTLIVE_OT_send_command,
    ROBOTLIVE_OT_action,
    ROBOTLIVE_OT_stop,
    ROBOTLIVE_OT_create_target,
    ROBOTLIVE_OT_target_action,
    ROBOTLIVE_OT_snap_target,
    ROBOTLIVE_OT_bind_selected,
    ROBOTLIVE_OT_record,
    ROBOTLIVE_PT_panel,
    ROBOTLIVE_PT_item_panel,
)


def register():
    global _addon_active
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    Scene = bpy.types.Scene
    Scene.robot_live_host = StringProperty(name="Host", default=os.environ.get("ROBOT_LIVE_HOST", "127.0.0.1"))
    Scene.robot_live_port = IntProperty(name="Port", default=int(os.environ.get("ROBOT_LIVE_PORT", "8765")), min=1, max=65535)
    Scene.robot_live_command = StringProperty(name="Command", default="抓取")
    Scene.robot_live_status = StringProperty(name="Status", default="Disconnected")
    Scene.robot_live_last_result = StringProperty(name="Last Result", default="Ready")
    Scene.robot_live_offset = FloatVectorProperty(name="Offset", size=3, subtype="TRANSLATION", update=_calibration_updated)
    Scene.robot_live_scale = FloatProperty(name="Scale", default=1.0, min=0.0001, update=_calibration_updated)
    Scene.robot_live_rotation_z = FloatProperty(name="Z Rotation (deg)", default=0.0, update=_calibration_updated)
    Scene.robot_live_add_workbench = BoolProperty(name="Add Demo Workbench", default=True)
    Scene.robot_live_object_name = StringProperty(name="Bound Object", default="")
    Scene.robot_live_active_object = EnumProperty(
        name="Active Object",
        items=_active_object_items,
        update=_active_object_updated,
    )
    Scene.robot_live_grasp_planner = StringProperty(name="Grasp Planner", default="")
    Scene.robot_live_grasp_score = FloatProperty(name="Grasp Score", default=0.0)
    Scene.robot_live_recording = BoolProperty(name="Recording", default=False)
    Scene.robot_live_record_count = IntProperty(name="Recorded States", default=0)
    Scene.robot_live_sequence = IntProperty(name="Sequence", default=0)
    Scene.robot_live_grasped = BoolProperty(name="Grasped", default=False)
    Scene.robot_live_left_force = FloatProperty(name="Left Contact Force", default=0.0, unit="NONE")
    Scene.robot_live_right_force = FloatProperty(name="Right Contact Force", default=0.0, unit="NONE")
    Scene.robot_live_contact_valid = BoolProperty(name="Force Closure", default=False)
    Scene.robot_live_target_operation = EnumProperty(
        name="Target Operation",
        items=(
            ("move_to", "Move EE", "Check end-effector movement"),
            ("place_at", "Place", "Check supported placement"),
            ("push_to", "Push", "Check contact-driven push"),
            ("rotate_to", "Rotate", "Check grasped-object rotation"),
            ("pick", "Pick", "Check whether the current object is graspable"),
        ),
        default="move_to",
    )
    Scene.robot_live_target_status = StringProperty(name="Target Status", default="")
    _addon_active = True
    if not bpy.app.timers.is_registered(_process_network_events):
        bpy.app.timers.register(_process_network_events, first_interval=0.1, persistent=True)


def unregister():
    global _addon_active
    scene = getattr(bpy.context, "scene", None)
    if scene is not None and _runtime.recording:
        _finish_recording(scene)
    _addon_active = False
    _client.disconnect(notify=False)
    if bpy.app.timers.is_registered(_process_network_events):
        bpy.app.timers.unregister(_process_network_events)
    for name in (
        "robot_live_host",
        "robot_live_port",
        "robot_live_command",
        "robot_live_status",
        "robot_live_last_result",
        "robot_live_offset",
        "robot_live_scale",
        "robot_live_rotation_z",
        "robot_live_add_workbench",
        "robot_live_object_name",
        "robot_live_active_object",
        "robot_live_grasp_planner",
        "robot_live_grasp_score",
        "robot_live_recording",
        "robot_live_record_count",
        "robot_live_sequence",
        "robot_live_grasped",
        "robot_live_left_force",
        "robot_live_right_force",
        "robot_live_contact_valid",
        "robot_live_target_operation",
        "robot_live_target_status",
    ):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
