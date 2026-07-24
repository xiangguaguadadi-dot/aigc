"""Launch Blender to create a high-quality robot interaction replay."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def render_run(
    run_dir: str | Path,
    blender_bin: str | Path | None = None,
    environment: str | Path | None = None,
    engine: str = "eevee",
    samples: int = 16,
    resolution: tuple[int, int] = (1280, 720),
    preview_frame: int = 0,
    world_offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    world_scale: float = 1.0,
    world_rotation_z: float = 0.0,
    render_video: bool = False,
) -> dict[str, Path]:
    run_dir = Path(run_dir).resolve()
    for required in ("trajectory.json", "scene_manifest.json"):
        if not (run_dir / required).exists():
            raise FileNotFoundError(run_dir / required)

    blender = Path(blender_bin or _default_blender_bin()).expanduser()
    if not blender.exists():
        raise FileNotFoundError(
            f"Blender executable not found: {blender}. Set BLENDER_BIN or pass --blender-bin."
        )
    replay_script = Path(__file__).resolve().parent.parent / "blender" / "replay_robot_run.py"
    command = [
        str(blender),
        "--background",
        "--python",
        str(replay_script),
        "--",
        "--run-dir",
        str(run_dir),
        "--engine",
        engine,
        "--samples",
        str(samples),
        "--resolution-x",
        str(resolution[0]),
        "--resolution-y",
        str(resolution[1]),
        "--preview-frame",
        str(preview_frame),
        "--world-offset",
        ",".join(str(value) for value in world_offset),
        "--world-scale",
        str(world_scale),
        "--world-rotation-z",
        str(world_rotation_z),
    ]
    if environment:
        command.extend(["--environment", str(Path(environment).resolve())])
    if render_video:
        command.append("--video")

    print(f"Starting Blender replay: {run_dir}")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Blender replay failed.\n"
            f"stdout:\n{result.stdout[-5000:]}\n"
            f"stderr:\n{result.stderr[-5000:]}"
        )
    if result.stdout:
        print(result.stdout[-2500:])

    render_dir = run_dir / "render"
    outputs = {
        "blend": render_dir / "robot_replay.blend",
        "preview": render_dir / "preview.png",
        "report": render_dir / "render_report.json",
    }
    if render_video:
        outputs["video"] = render_dir / "robot_interaction.mp4"
    missing = [path for path in outputs.values() if not path.exists()]
    if missing:
        raise RuntimeError(f"Blender exited successfully but outputs are missing: {missing}")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a recorded robot run with Blender")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--blender-bin", default=None)
    parser.add_argument("--environment", default=None)
    parser.add_argument("--engine", choices=["eevee", "cycles"], default="eevee")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--resolution", type=_resolution, default=(1280, 720))
    parser.add_argument("--preview-frame", type=int, default=0)
    parser.add_argument("--world-offset", type=_xyz, default=(0.0, 0.0, 0.0))
    parser.add_argument("--world-scale", type=float, default=1.0)
    parser.add_argument("--world-rotation-z", type=float, default=0.0)
    parser.add_argument("--video", action="store_true")
    args = parser.parse_args()

    outputs = render_run(
        run_dir=args.run_dir,
        blender_bin=args.blender_bin,
        environment=args.environment,
        engine=args.engine,
        samples=args.samples,
        resolution=args.resolution,
        preview_frame=args.preview_frame,
        world_offset=args.world_offset,
        world_scale=args.world_scale,
        world_rotation_z=args.world_rotation_z,
        render_video=args.video,
    )
    print("Render complete:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")


def _default_blender_bin() -> str:
    configured = os.environ.get("BLENDER_BIN")
    if configured:
        return configured
    try:
        from video_to_3d.config import BLENDER_BIN

        return BLENDER_BIN
    except ImportError:
        return r"C:\Users\NewUser\Applications\blender-4.5.11-windows-x64\blender.exe"


def _xyz(value: str) -> tuple[float, float, float]:
    values = tuple(float(part.strip()) for part in value.split(","))
    if len(values) != 3:
        raise argparse.ArgumentTypeError("expected x,y,z")
    return values


def _resolution(value: str) -> tuple[int, int]:
    normalized = value.lower().replace("x", ",")
    values = tuple(int(part.strip()) for part in normalized.split(","))
    if len(values) != 2 or min(values) <= 0:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT")
    return values


if __name__ == "__main__":
    main()
