"""Load the workspace Blender add-on and optionally auto-connect to PyBullet."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import bpy


def main():
    args = _parse_args()
    if args.add_workbench or args.environment:
        _clear_scene_objects()
    project_root = Path(__file__).resolve().parent.parent.parent
    addon_parent = project_root / "simulation" / "blender_addon"
    if str(addon_parent) not in sys.path:
        sys.path.insert(0, str(addon_parent))

    import robot_interaction

    if hasattr(bpy.types, "ROBOTLIVE_PT_panel"):
        try:
            robot_interaction.unregister()
        except Exception:
            pass
        robot_interaction = importlib.reload(robot_interaction)
    robot_interaction.register()

    scene = bpy.context.scene
    scene.robot_live_host = args.host
    scene.robot_live_port = args.port
    scene.robot_live_add_workbench = args.add_workbench
    if args.environment:
        _import_environment(Path(args.environment).resolve())

    if args.auto_connect:
        def connect_once():
            try:
                robot_interaction.connect_to_server(args.host, args.port)
            except Exception as exc:
                scene.robot_live_status = "Error"
                scene.robot_live_last_result = str(exc)
            return None

        bpy.app.timers.register(connect_once, first_interval=0.5)
    print(f"ROBOT_LIVE_ADDON_READY {args.host}:{args.port}")


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--environment", default=None)
    parser.add_argument("--add-workbench", action="store_true")
    parser.add_argument("--auto-connect", action="store_true")
    return parser.parse_args(argv)


def _import_environment(path):
    extension = path.suffix.lower()
    if extension in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif extension == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    elif extension == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise ValueError(f"Unsupported interactive environment: {path}")


def _clear_scene_objects():
    """Remove Blender's startup Cube/Camera/Light before loading a live scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


if __name__ == "__main__":
    main()
