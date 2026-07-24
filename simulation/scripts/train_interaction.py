"""Train and evaluate the robot pick interaction policy.

Usage:
    python -m simulation.scripts.train_interaction --episodes 5 --no-gui
    python -m simulation.scripts.train_interaction --object outputs/.../export/asset.glb
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Part 3 robot interaction training")
    parser.add_argument("--object", "-o", default=None, help="Optional GLB/URDF object path")
    parser.add_argument("--episodes", "-n", type=int, default=8, help="Demonstration episodes")
    parser.add_argument("--eval-episodes", type=int, default=4, help="Imitation evaluation episodes")
    parser.add_argument("--no-gui", action="store_true", help="Run PyBullet headless")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output-dir", default="outputs/robot_training", help="Training output directory")
    parser.add_argument("--noise", type=float, default=0.004, help="Expert action noise in meters")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(project_root))

    from simulation.policies import ScriptedPickPolicy
    from simulation.tasks.pick import PandaPickTask, PickTaskConfig
    from simulation.training import InteractionTrainer, TrainerConfig

    task_config = PickTaskConfig(
        gui=not args.no_gui,
        object_path=args.object,
        seed=args.seed,
    )
    task = PandaPickTask(task_config)
    trainer = InteractionTrainer(
        task,
        TrainerConfig(
            episodes=args.episodes,
            output_dir=Path(args.output_dir),
        ),
    )

    print("=" * 60)
    print("Part 3: robot architecture + interaction training")
    print("=" * 60)
    print(f"Output: {trainer.run_dir}")

    expert = ScriptedPickPolicy(
        action_scale=task_config.action_scale,
        noise_std=args.noise,
        seed=args.seed,
    )
    demo = trainer.collect(expert, label="expert")
    imitation = trainer.train_imitation(demo["observations"], demo["actions"])

    trainer.config.episodes = args.eval_episodes
    evaluation = trainer.collect(imitation, label="imitation")
    task.close()

    print("\nResults")
    print(f"  Expert success:    {demo['summary']['success_rate']:.2%}")
    print(f"  Imitation success: {evaluation['summary']['success_rate']:.2%}")
    print(f"  Saved trajectories and policy under: {trainer.run_dir}")


if __name__ == "__main__":
    main()
