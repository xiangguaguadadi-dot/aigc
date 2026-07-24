"""Start the PyBullet service and an interactive Blender session together."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch live robot interaction in Blender")
    parser.add_argument("--environment", default=None, help="BLEND, GLB, GLTF, OBJ, or FBX environment")
    parser.add_argument("--object", default=None, help="Manipulated GLB, GLTF, OBJ, or URDF")
    parser.add_argument("--scene-manifest", default=None, help="Prepared multi-object scene manifest")
    parser.add_argument("--object-scale", type=float, default=0.05)
    parser.add_argument("--object-mass", type=float, default=0.5)
    parser.add_argument("--object-friction", type=float, default=0.9)
    parser.add_argument("--object-position", default="0.5,0,0.66")
    parser.add_argument("--scene-profile", choices=["tabletop", "floor"], default="tabletop")
    parser.add_argument("--robot-base", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--stream-fps", type=int, default=30)
    parser.add_argument("--motion-steps", type=int, default=80)
    parser.add_argument("--blender-bin", default=None)
    parser.add_argument("--no-auto-connect", action="store_true")
    args = parser.parse_args()
    robot_base = args.robot_base or (
        "0,-0.35,0.626" if args.scene_profile == "tabletop" else "0,-0.35,0"
    )
    if args.object_scale <= 0 or args.object_mass <= 0 or args.object_friction < 0:
        parser.error("object-scale and object-mass must be positive; friction must be non-negative")

    if _port_is_open(args.host, args.port):
        raise RuntimeError(f"Port {args.host}:{args.port} is already in use")
    blender = Path(args.blender_bin or _default_blender_bin()).expanduser().resolve()
    if not blender.exists():
        raise FileNotFoundError(f"Blender executable not found: {blender}")
    environment = Path(args.environment).expanduser().resolve() if args.environment else None
    if environment and not environment.exists():
        raise FileNotFoundError(environment)

    server_command = [
        sys.executable,
        "-u",
        "-m",
        "simulation.scripts.robot_server",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--object-scale",
        str(args.object_scale),
        "--object-mass",
        str(args.object_mass),
        "--object-friction",
        str(args.object_friction),
        "--object-position",
        args.object_position,
        "--scene-profile",
        args.scene_profile,
        "--robot-base",
        robot_base,
        "--speed",
        str(args.speed),
        "--stream-fps",
        str(args.stream_fps),
        "--motion-steps",
        str(args.motion_steps),
    ]
    if args.object:
        server_command.extend(["--object", str(Path(args.object).expanduser().resolve())])
    if args.scene_manifest:
        manifest = Path(args.scene_manifest).expanduser().resolve()
        if not manifest.exists():
            raise FileNotFoundError(manifest)
        server_command.extend(["--scene-manifest", str(manifest)])

    project_root = Path(__file__).resolve().parent.parent.parent
    start_script = project_root / "simulation" / "blender" / "start_live_session.py"
    blender_command = [str(blender)]
    if environment and environment.suffix.lower() == ".blend":
        blender_command.append(str(environment))
    blender_command.extend(
        [
            "--python",
            str(start_script),
            "--",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
    )
    if not environment:
        blender_command.append("--add-workbench")
    elif environment.suffix.lower() != ".blend":
        blender_command.extend(["--environment", str(environment)])
    if not args.no_auto_connect:
        blender_command.append("--auto-connect")

    server = subprocess.Popen(server_command, cwd=project_root)
    try:
        _wait_for_server(server, args.host, args.port, timeout=30.0)
        print(f"Opening Blender; robot server PID={server.pid}")
        result = subprocess.run(blender_command, cwd=project_root)
        if result.returncode != 0:
            raise RuntimeError(f"Blender exited with code {result.returncode}")
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                server.kill()


def _wait_for_server(process, host, port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Robot server exited with code {process.returncode}")
        if _port_is_open(host, port):
            return
        time.sleep(0.1)
    raise TimeoutError("Robot server did not become ready")


def _port_is_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except OSError:
        return False


def _default_blender_bin():
    configured = os.environ.get("BLENDER_BIN")
    if configured:
        return configured
    try:
        from video_to_3d.config import BLENDER_BIN

        return BLENDER_BIN
    except ImportError:
        return r"C:\Users\NewUser\Applications\blender-4.5.11-windows-x64\blender.exe"


if __name__ == "__main__":
    main()
