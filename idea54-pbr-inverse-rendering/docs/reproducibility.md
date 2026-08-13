# Reproducibility

Every run records the resolved seed, Git commit, Python, PyTorch, CUDA,
nvdiffrast, GPU, input hashes, geometry hashes, per-step losses, learned
parameters, and metrics. Runs fail if geometry hashes differ.

Use the same CUDA image and deterministic seed for paired comparisons. Some GPU
rasterization operations may not be bitwise deterministic across GPU
architectures; compare within one environment and report the environment.

Runtime code performs no network access. Dependency installation is separate
from experiments. Do not commit `runs/`, user assets, weights, or caches.
