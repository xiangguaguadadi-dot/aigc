"""Normalize a visual GLB asset and render a verification preview in Blender."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def parse_args() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blend-output", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rotate-x-degrees", type=float, default=0.0)
    return parser.parse_args(args)


def world_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    corners = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    minimum = Vector(tuple(min(point[i] for point in corners) for i in range(3)))
    maximum = Vector(tuple(max(point[i] for point in corners) for i in range(3)))
    return minimum, maximum


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_preview_scene(extents: Vector) -> None:
    horizontal = max(extents.x, extents.y)

    bpy.ops.mesh.primitive_plane_add(size=max(horizontal * 4.0, 2.0), location=(0, 0, -0.003))
    floor = bpy.context.object
    floor.name = "preview_floor"
    material = bpy.data.materials.new("preview_floor_material")
    material.diffuse_color = (0.14, 0.15, 0.16, 1.0)
    floor.data.materials.append(material)

    target = Vector((0.0, 0.0, extents.z * 0.45))
    distance = max(extents) * 2.2
    bpy.ops.object.camera_add(location=(distance * 0.85, -distance * 0.85, distance * 0.65))
    camera = bpy.context.object
    camera.name = "preview_camera"
    camera.data.lens = 55
    look_at(camera, target)
    bpy.context.scene.camera = camera

    for index, (location, energy, size) in enumerate(
        [
            ((distance, -distance, distance * 1.4), 900.0, max(horizontal, 1.0)),
            ((-distance * 0.7, -distance * 0.2, distance), 500.0, max(horizontal, 1.0)),
        ]
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = f"preview_light_{index + 1}"
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        look_at(light, target)


def main() -> None:
    args = parse_args()
    for path in (args.output, args.blend_output, args.preview, args.report):
        path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    bpy.ops.import_scene.gltf(filepath=str(args.input.resolve()))
    imported = list(scene.objects)
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("Imported asset contains no mesh objects")

    imported_min, imported_max = world_bounds(meshes)
    roots = [obj for obj in imported if obj.parent is None]
    if args.rotate_x_degrees:
        rotation = Matrix.Rotation(math.radians(args.rotate_x_degrees), 4, "X")
        for obj in roots:
            obj.matrix_world = rotation @ obj.matrix_world
        bpy.context.view_layer.update()

    for index, obj in enumerate(meshes, start=1):
        obj.name = f"{args.asset_id}_mesh_{index:03d}"
        if obj.data:
            obj.data.name = f"{args.asset_id}_geometry_{index:03d}"

    before_min, before_max = world_bounds(meshes)
    delta = Vector(
        (
            -(before_min.x + before_max.x) / 2.0,
            -(before_min.y + before_max.y) / 2.0,
            -before_min.z,
        )
    )
    for obj in roots:
        obj.location += delta
    bpy.context.view_layer.update()

    after_min, after_max = world_bounds(meshes)
    extents = after_max - after_min

    for obj in scene.objects:
        obj.select_set(False)
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.export_scene.gltf(
        filepath=str(args.output.resolve()),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(args.blend_output.resolve()))

    add_preview_scene(extents)
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(args.preview.resolve())
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("preview_world")
    scene.world.color = (0.035, 0.04, 0.05)
    bpy.ops.render.render(write_still=True)

    report = {
        "asset_id": args.asset_id,
        "input": str(args.input.resolve()),
        "output": str(args.output.resolve()),
        "blend_output": str(args.blend_output.resolve()),
        "preview": str(args.preview.resolve()),
        "blender_version": bpy.app.version_string,
        "units": "m",
        "coordinate_system": "right-handed, +Z up",
        "scale_status": "unscaled: no measured dimension supplied",
        "mesh_count": len(meshes),
        "vertex_count": sum(len(obj.data.vertices) for obj in meshes),
        "polygon_count": sum(len(obj.data.polygons) for obj in meshes),
        "bounds_imported": [list(imported_min), list(imported_max)],
        "rotate_x_degrees": args.rotate_x_degrees,
        "bounds_before": [list(before_min), list(before_max)],
        "translation_applied": list(delta),
        "bounds_after": [list(after_min), list(after_max)],
        "extents_after": list(extents),
    }

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.output.resolve()))
    roundtrip_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not roundtrip_meshes:
        raise RuntimeError("Round-trip GLB contains no mesh objects")
    roundtrip_min, roundtrip_max = world_bounds(roundtrip_meshes)
    report["roundtrip"] = {
        "passed": True,
        "mesh_count": len(roundtrip_meshes),
        "vertex_count": sum(len(obj.data.vertices) for obj in roundtrip_meshes),
        "polygon_count": sum(len(obj.data.polygons) for obj in roundtrip_meshes),
        "bounds": [list(roundtrip_min), list(roundtrip_max)],
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
