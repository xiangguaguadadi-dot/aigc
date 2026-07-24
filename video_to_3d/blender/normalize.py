"""Stage 7: Blender background normalization.

Called as: blender.exe --background --python normalize.py -- <mesh_path> <output_dir>

Adapted from the existing scripts/blender/normalize_asset.py approach.
Handles: import → center → z=0 → save .blend → export GLB → render preview.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path


def run_blender(mesh_path: str, output_dir: str, blender_bin: str):
    """Launch Blender in background mode to normalize a mesh.

    Args:
        mesh_path: Absolute path to the input mesh (PLY/OBJ)
        output_dir: Absolute path to the output directory
        blender_bin: Path to Blender executable
    """
    script_path = os.path.abspath(__file__)
    import subprocess
    cmd = [
        blender_bin,
        "--background",
        "--python", script_path,
        "--",
        mesh_path,
        output_dir,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"Blender normalization failed:\n"
            f"stdout: {result.stdout[-2000:]}\n"
            f"stderr: {result.stderr[-2000:]}"
        )
    return result.stdout


# ── Blender API calls (only when running inside Blender) ──

def _blender_main():
    """Entry point when script is run inside Blender --background."""
    import bpy

    argv = sys.argv[sys.argv.index("--") + 1:]
    if len(argv) < 2:
        print("Usage: blender --background --python normalize.py -- <mesh_path> <output_dir>")
        sys.exit(1)

    mesh_path = argv[0]
    output_dir = Path(argv[1])
    output_dir.mkdir(parents=True, exist_ok=True)

    mesh_stem = Path(mesh_path).stem

    # Clear factory scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Import mesh
    ext = Path(mesh_path).suffix.lower()
    if ext in {".ply"}:
        bpy.ops.wm.ply_import(filepath=mesh_path)
    elif ext in {".obj"}:
        bpy.ops.wm.obj_import(filepath=mesh_path)
    elif ext in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=mesh_path)
    else:
        # Try generic import
        bpy.ops.wm.obj_import(filepath=mesh_path)

    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Record original mesh stats
    mesh_data = obj.data
    orig_verts = len(mesh_data.vertices)
    orig_faces = len(mesh_data.polygons)
    print(f"Imported mesh: {orig_verts} vertices, {orig_faces} faces")

    # Center horizontally (keep Z as-is for now)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    obj.location.x = 0
    obj.location.y = 0

    # Move bottom to z=0
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bbox_corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    min_z = min(c.z for c in bbox_corners)
    obj.location.z -= min_z

    # Apply transforms
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Save .blend
    blend_dir = output_dir / "blender"
    blend_dir.mkdir(parents=True, exist_ok=True)
    blend_path = blend_dir / "normalized.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Saved .blend: {blend_path}")

    # Export GLB
    export_dir = output_dir / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    glb_path = export_dir / f"{mesh_stem}.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        use_selection=False,
        export_texcoords=True,
        export_normals=True,
        export_draco_mesh_compression_enable=False,
    )
    print(f"Exported GLB: {glb_path}")

    # Render preview
    preview_dir = output_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = preview_dir / "preview.png"

    # Set up camera
    bpy.ops.object.camera_add(location=(2.5, -2.5, 1.5))
    camera = bpy.context.active_object
    bpy.context.scene.camera = camera

    # Point camera at origin
    direction = mathutils.Vector((0, 0, 0)) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # Lighting: area light from above-right
    bpy.ops.object.light_add(type="AREA", location=(2, -2, 3))
    area_light = bpy.context.active_object
    area_light.data.energy = 200
    area_light.data.size = 3

    # Fill light
    bpy.ops.object.light_add(type="AREA", location=(-2, 2, 1))
    fill_light = bpy.context.active_object
    fill_light.data.energy = 100
    fill_light.data.size = 3

    # Background
    if "World" not in bpy.data.worlds:
        world = bpy.data.worlds.new("preview_world")
        bpy.context.scene.world = world
    else:
        world = bpy.context.scene.world
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs["Strength"].default_value = 0.8
        bg_node.inputs["Color"].default_value = (0.2, 0.2, 0.2, 1.0)

    # Render settings
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.render.filepath = str(preview_path)
    bpy.context.scene.render.resolution_x = 800
    bpy.context.scene.render.resolution_y = 800
    bpy.context.scene.render.film_transparent = True
    bpy.context.scene.cycles.samples = 64  # fast preview
    bpy.context.scene.render.image_settings.file_format = "PNG"

    bpy.ops.render.render(write_still=True)
    print(f"Preview rendered: {preview_path}")

    # Report
    report = {
        "input": mesh_path,
        "imported_vertices": orig_verts,
        "imported_faces": orig_faces,
        "output_blend": str(blend_path),
        "output_glb": str(glb_path),
        "output_preview": str(preview_path),
        "coordinate_system": "right-handed, +Z up",
        "center_xy": True,
        "bottom_z0": True,
    }

    report_path = blend_dir / "normalization_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved: {report_path}")


# ── Module-level entry ──

if __name__ == "__main__":
    # Check if running inside Blender
    try:
        import bpy
        import mathutils
        _blender_main()
    except ImportError:
        # Running as Python script - print usage
        print("This script is designed to run inside Blender:")
        print("  blender --background --python normalize.py -- <mesh_path> <output_dir>")
        print()
        print("Or use run_blender() from another Python script to call it via subprocess.")
