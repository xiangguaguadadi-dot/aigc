"""Part 3: Virtual robot architecture and interaction training.

PyBullet-based simulation for robot-object interaction. It can load
reconstructed GLB objects, expose a compact task API, and collect/evaluate
interaction trajectories.
"""

__version__ = "0.1.0"

from simulation.tasks import PandaPickTask, PickTaskConfig

__all__ = ["PandaPickTask", "PickTaskConfig"]
