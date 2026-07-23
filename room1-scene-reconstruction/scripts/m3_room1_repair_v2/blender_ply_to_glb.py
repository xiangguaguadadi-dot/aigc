#!/usr/bin/env python3
"""Run inside Blender to import one PLY and export a binary glTF."""

import sys
from pathlib import Path

import bpy


def main() -> None:
    args = sys.argv[sys.argv.index('--') + 1:]
    if len(args) != 2:
        raise SystemExit('usage: blender --background --python script -- input.ply output.glb')
    source, target = map(Path, args)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.ply_import(filepath=str(source))
    objects = list(bpy.context.selected_objects)
    if not objects:
        raise RuntimeError(f'Blender imported no objects from {source}')
    for obj in objects:
        if obj.type == 'MESH':
            obj.name = target.stem
    bpy.ops.export_scene.gltf(
        filepath=str(target),
        export_format='GLB',
        use_selection=True,
        export_apply=True,
    )
    print(f'exported {target} from {source}')


if __name__ == '__main__':
    main()
