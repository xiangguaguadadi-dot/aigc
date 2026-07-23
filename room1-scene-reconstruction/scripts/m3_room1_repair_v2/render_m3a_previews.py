#!/usr/bin/env python3
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def look_at(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat('-Z', 'Y').to_euler()


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    if len(args) != 2:
        raise SystemExit('usage: blender --background --python script -- scene.glb renders_dir')
    scene_path, out_dir = Path(args[0]), Path(args[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(scene_path))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError('no mesh imported')
    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    lo = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    hi = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    target = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.9, 2.0)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    world = scene.world or bpy.data.worlds.new('World')
    scene.world = world
    world.color = (0.055, 0.055, 0.055)
    bpy.ops.object.camera_add(location=target + Vector((0, -radius, radius * 0.25)))
    camera = bpy.context.object
    camera.data.lens = 42
    scene.camera = camera
    bpy.ops.object.light_add(type='AREA', location=target + Vector((0, -radius * 0.4, radius)))
    light = bpy.context.object
    light.data.energy = 1800
    light.data.shape = 'DISK'
    light.data.size = radius
    look_at(light, target)
    for i, angle in enumerate((0.0, 2.0943951024, 4.1887902048)):
        camera.location = target + Vector((math.sin(angle) * radius, -math.cos(angle) * radius, radius * 0.25))
        look_at(camera, target)
        scene.render.filepath = str(out_dir / f'm3a_preview_{i:02d}.png')
        bpy.ops.render.render(write_still=True)
    print(f'rendered previews in {out_dir}')


if __name__ == '__main__':
    main()
