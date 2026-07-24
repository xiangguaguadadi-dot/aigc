"""Execute robot commands and record a Blender-ready trajectory."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from simulation.env import SimulationEnv
from simulation.recording import TrajectoryRecorder
from simulation.robots.panda import PandaRobot
from simulation.scripts.command_robot import CommandScene, _parse_xyz, _split_commands


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a command-driven Panda interaction")
    parser.add_argument(
        "--commands",
        default="pick; lift; place right; home",
        help="Semicolon-separated Chinese or English robot commands",
    )
    parser.add_argument("--object", "-o", default=None, help="GLB, GLTF, OBJ, or URDF object")
    parser.add_argument("--object-scale", type=float, default=0.05)
    parser.add_argument("--object-position", default="0.5,0,0.66")
    parser.add_argument("--environment", default=None, help="Optional Blender/GLB modeled environment")
    parser.add_argument("--robot-base", default="0,-0.35,0.626")
    parser.add_argument("--output-root", default="outputs/robot_runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--fps", type=int, default=30, help="Replay sampling frame rate")
    parser.add_argument("--dt", type=float, default=1 / 240)
    parser.add_argument("--gui", action="store_true", help="Also show the PyBullet window")
    parser.add_argument("--step-delay", type=float, default=0.0)
    parser.add_argument("--render", action="store_true", help="Render a Blender preview after recording")
    parser.add_argument("--video", action="store_true", help="With --render, also render MP4")
    args = parser.parse_args()

    commands = _split_commands(args.commands)
    if not commands:
        parser.error("--commands must contain at least one command")
    run_id = args.run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir = Path(args.output_root) / run_id

    scene = CommandScene(
        p=__import__("pybullet"),
        env=SimulationEnv(gui=args.gui),
        robot_base=_parse_xyz(args.robot_base),
        object_path=Path(args.object).resolve() if args.object else None,
        object_scale=args.object_scale,
        step_delay=args.step_delay if args.gui else 0.0,
        dt=args.dt,
        object_position=_parse_xyz(args.object_position),
    )
    recorder = TrajectoryRecorder(
        run_dir=run_dir,
        simulation_dt=args.dt,
        output_fps=args.fps,
        environment_path=args.environment,
    )

    recording_started = False
    try:
        scene.setup(PandaRobot)
        recorder.start(scene)
        recording_started = True
        scene.frame_observer = recorder.on_simulation_step
        for command in commands:
            print(f"Command: {command}")
            recorder.begin_command(command, scene)
            succeeded = scene.execute(command)
            recorder.end_command(scene, status="completed" if succeeded else "failed")
            if not succeeded:
                raise ValueError(f"Robot command failed: {command}")
        paths = recorder.save()
    except Exception:
        if recording_started:
            recorder.save()
        raise
    finally:
        scene.close()

    print(f"Recorded {len(recorder.frames)} frames to: {run_dir.resolve()}")
    for name, path in paths.items():
        print(f"  {name}: {path}")

    if args.render:
        from simulation.scripts.render_robot_run_blender import render_run

        render_run(run_dir=run_dir, render_video=args.video)


if __name__ == "__main__":
    main()
