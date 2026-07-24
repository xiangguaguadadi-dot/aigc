"""Build and render a polished Blender replay from a recorded robot run.

Called by Blender:
    blender --background --python replay_robot_run.py -- --run-dir <directory>
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    args = _parse_args()
    run_dir = Path(args.run_dir).resolve()
    trajectory = _read_json(run_dir / "trajectory.json")
    manifest = _read_json(run_dir / "scene_manifest.json")
    frames = trajectory.get("frames", [])
    if not frames:
        raise RuntimeError(f"No trajectory frames found in {run_dir}")

    environment = args.environment or manifest.get("environment", {}).get("source_path")
    environment_path = Path(environment).resolve() if environment else None
    if environment_path and not environment_path.exists():
        raise FileNotFoundError(f"Environment not found: {environment_path}")

    _prepare_scene(environment_path)
    replay_collection = _new_replay_collection()
    replay_root = _new_empty("Replay_World", replay_collection)
    replay_root.location = tuple(args.world_offset)
    replay_root.scale = (args.world_scale,) * 3
    replay_root.rotation_euler[2] = math.radians(args.world_rotation_z)

    if environment_path is None:
        _build_procedural_environment(replay_collection, replay_root)

    robot_objects = _build_robot(manifest, replay_collection, replay_root)
    object_root = _build_object(manifest, replay_collection, replay_root)
    _animate(robot_objects, object_root, frames)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = len(frames)
    scene.render.fps = int(trajectory.get("fps", 30))
    preview_frame = args.preview_frame
    if preview_frame <= 0:
        preview_frame = _best_preview_frame(frames)
    preview_frame = min(max(1, preview_frame), len(frames))

    angle = math.radians(args.world_rotation_z)
    local_target = Vector((0.35, -0.05, 0.88))
    rotated_target = Vector(
        (
            math.cos(angle) * local_target.x - math.sin(angle) * local_target.y,
            math.sin(angle) * local_target.x + math.cos(angle) * local_target.y,
            local_target.z,
        )
    )
    target = Vector(args.world_offset) + args.world_scale * rotated_target
    _build_camera_and_lighting(replay_collection, target, args.world_scale)
    _configure_render(scene, args)
    _set_linear_interpolation(robot_objects.values())
    _set_linear_interpolation([object_root])

    render_dir = run_dir / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    blend_path = render_dir / "robot_replay.blend"
    preview_path = render_dir / "preview.png"
    video_path = render_dir / "robot_interaction.mp4"

    scene.frame_set(preview_frame)
    scene.render.filepath = str(preview_path)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    bpy.ops.render.render(write_still=True)

    if args.video:
        scene.frame_set(1)
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
        scene.render.filepath = str(video_path)
        bpy.ops.render.render(animation=True)
        scene.render.image_settings.file_format = "PNG"

    report = {
        "run_dir": str(run_dir),
        "environment": str(environment_path) if environment_path else "procedural_workbench",
        "frame_count": len(frames),
        "fps": scene.render.fps,
        "preview_frame": preview_frame,
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "blend": str(blend_path),
        "preview": str(preview_path),
        "video": str(video_path) if args.video else None,
    }
    with (render_dir / "render_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"BLEND_OUTPUT={blend_path}")
    print(f"PREVIEW_OUTPUT={preview_path}")
    if args.video:
        print(f"VIDEO_OUTPUT={video_path}")


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Replay a recorded Panda run in Blender")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--environment", default=None)
    parser.add_argument("--engine", choices=["eevee", "cycles"], default="eevee")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--resolution-x", type=int, default=1280)
    parser.add_argument("--resolution-y", type=int, default=720)
    parser.add_argument("--preview-frame", type=int, default=0)
    parser.add_argument("--world-offset", type=_xyz, default=(0.0, 0.0, 0.0))
    parser.add_argument("--world-scale", type=float, default=1.0)
    parser.add_argument("--world-rotation-z", type=float, default=0.0)
    parser.add_argument("--video", action="store_true")
    args = parser.parse_args(argv)
    if args.world_scale <= 0:
        parser.error("--world-scale must be positive")
    return args


def _prepare_scene(environment_path: Path | None) -> None:
    if environment_path and environment_path.suffix.lower() == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(environment_path))
        old_collection = bpy.data.collections.get("Robot_Replay")
        if old_collection is not None:
            _remove_collection(old_collection)
        return

    bpy.ops.wm.read_factory_settings(use_empty=True)
    if environment_path is not None:
        _import_scene_asset(environment_path)


def _new_replay_collection():
    collection = bpy.data.collections.new("Robot_Replay")
    bpy.context.scene.collection.children.link(collection)
    return collection


def _build_robot(manifest, collection, replay_root):
    shape_descriptions = manifest["robot"]["visual_shapes"]
    robot_objects = {}
    for shape in shape_descriptions:
        pose_root = _new_empty(shape["id"], collection)
        pose_root.parent = replay_root
        mesh_path = Path(shape["mesh_path"]) if shape.get("mesh_path") else None
        imported = []
        if mesh_path and mesh_path.exists() and mesh_path.suffix.lower() == ".obj":
            imported = _import_obj(mesh_path)
        if not imported:
            imported = [_fallback_robot_part(shape, collection)]
        for mesh_object in imported:
            _move_to_collection(mesh_object, collection)
            mesh_object.parent = pose_root
            mesh_object["robot_link"] = shape["link_name"]
            _polish_mesh(mesh_object)
        robot_objects[shape["id"]] = pose_root
    return robot_objects


def _build_object(manifest, collection, replay_root):
    object_root = _new_empty("Manipulated_Object", collection)
    object_root.parent = replay_root
    object_info = manifest.get("object", {})
    source = object_info.get("source_path")
    imported = []
    if source:
        source_path = Path(source)
        if source_path.exists():
            imported = _import_object_asset(source_path)
    if imported:
        for obj in imported:
            _move_to_collection(obj, collection)
            if obj.parent is None:
                obj.parent = object_root
        scale = float(object_info.get("scale", 1.0))
        object_root.scale = (scale, scale, scale)
    else:
        size = object_info.get("fallback_size", [0.05, 0.05, 0.05])
        material = _material("Object_Red", (0.72, 0.035, 0.025, 1.0), metallic=0.08, roughness=0.26)
        cube = _box("Demo_Object", size, (0.0, 0.0, 0.0), material, collection, bevel=0.006)
        cube.parent = object_root
    return object_root


def _animate(robot_objects, object_root, frames) -> None:
    for output_frame, state in enumerate(frames, start=1):
        for shape_id, pose in state["robot_links"].items():
            obj = robot_objects.get(shape_id)
            if obj is not None:
                _set_pose_and_keyframe(obj, pose, output_frame)
        _set_pose_and_keyframe(object_root, state["object"], output_frame)


def _set_pose_and_keyframe(obj, pose, frame: int) -> None:
    obj.location = tuple(pose["position"])
    quaternion = pose["orientation"]
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (quaternion[3], quaternion[0], quaternion[1], quaternion[2])
    obj.keyframe_insert(data_path="location", frame=frame, group="Replay Pose")
    obj.keyframe_insert(data_path="rotation_quaternion", frame=frame, group="Replay Pose")


def _build_procedural_environment(collection, replay_root) -> None:
    floor_material = _material("Floor", (0.095, 0.11, 0.12, 1.0), metallic=0.0, roughness=0.72)
    top_material = _material("Workbench_Top", (0.72, 0.76, 0.75, 1.0), metallic=0.18, roughness=0.32)
    frame_material = _material("Workbench_Frame", (0.055, 0.07, 0.08, 1.0), metallic=0.65, roughness=0.28)
    accent_material = _material("Mount_Accent", (0.035, 0.22, 0.18, 1.0), metallic=0.35, roughness=0.3)

    floor = _box("Studio_Floor", (4.5, 4.5, 0.03), (0.35, 0.0, -0.015), floor_material, collection, bevel=0.0)
    floor.parent = replay_root
    top = _box("Workbench_Top", (1.5, 1.0, 0.052), (0.5, 0.0, 0.6), top_material, collection, bevel=0.018)
    top.parent = replay_root
    for index, (x, y) in enumerate(((-0.15, -0.4), (-0.15, 0.4), (1.15, -0.4), (1.15, 0.4))):
        leg = _box(f"Workbench_Leg_{index + 1}", (0.1, 0.1, 0.58), (x, y, 0.29), frame_material, collection, bevel=0.012)
        leg.parent = replay_root
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.13, depth=0.028, location=(0.0, -0.35, 0.64))
    mount = bpy.context.active_object
    mount.name = "Robot_Mount"
    mount.data.materials.append(accent_material)
    _move_to_collection(mount, collection)
    mount.parent = replay_root


def _build_camera_and_lighting(collection, target: Vector, world_scale: float) -> None:
    scale = max(0.35, world_scale)
    bpy.ops.object.camera_add(location=target + Vector((1.75, -2.3, 1.05)) * scale)
    camera = bpy.context.active_object
    camera.name = "Replay_Camera"
    camera.data.lens = 55
    camera.data.sensor_width = 36
    _look_at(camera, target)
    _move_to_collection(camera, collection)
    bpy.context.scene.camera = camera

    lights = [
        ("Key_Light", (1.3, -1.8, 2.8), 900.0, 2.2, (1.0, 0.82, 0.68)),
        ("Fill_Light", (-1.5, -0.2, 1.8), 520.0, 2.6, (0.62, 0.78, 1.0)),
        ("Rim_Light", (1.4, 1.7, 2.3), 720.0, 1.8, (0.72, 1.0, 0.9)),
    ]
    for name, offset, energy, size, color in lights:
        bpy.ops.object.light_add(type="AREA", location=target + Vector(offset) * scale)
        light = bpy.context.active_object
        light.name = name
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size * scale
        light.data.color = color
        _look_at(light, target)
        _move_to_collection(light, collection)


def _configure_render(scene, args) -> None:
    scene.render.engine = "BLENDER_EEVEE_NEXT" if args.engine == "eevee" else "CYCLES"
    if args.engine == "eevee":
        scene.eevee.taa_render_samples = args.samples
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.film_transparent = False
        scene.render.resolution_percentage = 100
    else:
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = True
    scene.render.resolution_x = args.resolution_x
    scene.render.resolution_y = args.resolution_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    scene.render.fps_base = 1.0

    world = scene.world or bpy.data.worlds.new("Replay_World_Lighting")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.018, 0.024, 0.028, 1.0)
    background.inputs["Strength"].default_value = 0.32
    scene.view_settings.look = "AgX - Medium High Contrast"


def _import_obj(path: Path):
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    return list(set(bpy.data.objects) - before)


def _import_object_asset(path: Path):
    extension = path.suffix.lower()
    before = set(bpy.data.objects)
    if extension in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif extension == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    elif extension == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        print(f"Unsupported Blender object format {extension}; using fallback cube")
        return []
    return list(set(bpy.data.objects) - before)


def _import_scene_asset(path: Path) -> None:
    imported = _import_object_asset(path)
    if not imported:
        raise RuntimeError(f"Could not import modeled environment: {path}")


def _fallback_robot_part(shape, collection):
    dimensions = shape.get("dimensions", [0.08, 0.08, 0.12])
    radius = max(0.025, min(0.08, float(max(dimensions)) * 0.05))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=radius)
    obj = bpy.context.active_object
    obj.name = f"Fallback_{shape['link_name']}"
    obj.data.materials.append(_material("Robot_White", (0.82, 0.86, 0.86, 1.0), metallic=0.22, roughness=0.24))
    _move_to_collection(obj, collection)
    return obj


def _box(name, dimensions, location, material, collection, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    if bevel > 0:
        modifier = obj.modifiers.new("Edge Softness", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    _move_to_collection(obj, collection)
    return obj


def _material(name, color, metallic=0.0, roughness=0.4):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return material


def _polish_mesh(obj) -> None:
    if obj.type != "MESH":
        return
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    if not obj.data.materials:
        obj.data.materials.append(_material("Robot_White", (0.82, 0.86, 0.86, 1.0), metallic=0.22, roughness=0.24))


def _new_empty(name, collection):
    obj = bpy.data.objects.new(name, None)
    collection.objects.link(obj)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0.04
    return obj


def _move_to_collection(obj, collection) -> None:
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)


def _look_at(obj, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def _best_preview_frame(frames) -> int:
    for index in range(1, len(frames)):
        if frames[index - 1].get("grasped") and not frames[index].get("grasped"):
            return min(len(frames), index + 7)
    return max(range(len(frames)), key=lambda index: frames[index]["object"]["position"][2]) + 1


def _set_linear_interpolation(objects) -> None:
    for obj in objects:
        if obj.animation_data is None or obj.animation_data.action is None:
            continue
        try:
            for fcurve in obj.animation_data.action.fcurves:
                for keyframe in fcurve.keyframe_points:
                    keyframe.interpolation = "LINEAR"
        except AttributeError:
            pass


def _remove_collection(collection) -> None:
    for obj in list(collection.all_objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def _read_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _xyz(value: str):
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected x,y,z")
    return tuple(parts)


if __name__ == "__main__":
    main()
