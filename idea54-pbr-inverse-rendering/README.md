# Idea 5.4: Bounded PBR Inverse Rendering

A lightweight, model-free reproduction of geometry-frozen PBR inverse rendering.
Given a fixed triangle mesh, an initial per-vertex PBR material, a calibrated
camera, and one masked observation, the method optimizes bounded material
residuals together with low-dimensional illumination.

This repository does **not** download or redistribute TRELLIS.2, model weights,
datasets, HDRIs, or example assets. It generates a synthetic PBR benchmark in
code. Users who already have a TRELLIS.2 surface dump can adapt it explicitly.

## What is reproduced

- Geometry is excluded from the optimizer and checked with before/after hashes.
- Base color, metallic, and roughness are optimized around a strong prior.
- Illumination is a non-negative 12-direction basis plus ambient light,
  exposure, and white balance.
- Four paired methods share camera, seed, renderer, initialization, and budget:
  `prior`, `lighting_only`, `unbounded_pbr_light`, and `bounded_pbr_light`.
- Synthetic material ground truth distinguishes better condition-view fitting
  from actual material recovery.

This is a core-method reproduction, not a bitwise recovery of the lost runtime.
The historical 8.63% condition-view MAE change is context, not a target result.

## Requirements

- Linux
- NVIDIA GPU with CUDA (24 GB VRAM recommended for the formal configuration)
- Conda or an existing Python 3.10–3.12 CUDA environment

```bash
conda env create -f environment.cuda.yml
conda activate idea54
idea54 doctor
```

The environment installation fetches Python packages only. Runtime commands do
not fetch models or data.

## Quick start

```bash
idea54 make-synthetic \
  --config configs/synthetic_smoke.yaml \
  --output runs/bundles

idea54 validate runs/bundles/object_00_cube

idea54 run-paired \
  --bundle runs/bundles/object_00_cube \
  --config configs/synthetic_smoke.yaml \
  --output runs/smoke/object_00_cube

idea54 report \
  --runs runs/smoke \
  --output runs/smoke/report.md
```

Formal synthetic suite:

```bash
idea54 make-synthetic --config configs/synthetic_formal.yaml --output runs/formal_bundles
idea54 run-suite --bundles runs/formal_bundles --config configs/synthetic_formal.yaml --output runs/formal
idea54 report --runs runs/formal --output runs/formal/report.md
```

## Explicit TRELLIS.2 adapter

The adapter accepts a user-created NPZ with exactly named surface arrays:
`vertices`, `faces`, optional `vertex_normals`, `base_color`, `metallic`,
`roughness`, and `opacity`. It never guesses an O-Voxel channel layout.

```bash
idea54 adapt-trellis \
  --input /path/to/surface_dump.npz \
  --camera /path/to/camera.json \
  --observation /path/to/observation.png \
  --mask /path/to/mask.png \
  --upstream-commit YOUR_TRELLIS2_COMMIT \
  --output runs/real_bundle
```

Real-image runs without material ground truth may establish observation fit and
geometry preservation. They do not establish accurate real-world PBR recovery.

## Test boundaries

```bash
pytest -m "not gpu"
pytest -m gpu   # NVIDIA CUDA environment only
ruff check .
```

CPU CI checks schemas, bounds, hashes, statistics, and deterministic procedural
geometry. CUDA renderer and optimization tests must be run on an NVIDIA host.

See [the method](docs/method.md), [bundle contract](docs/asset_bundle_v1.md),
and [limitations](docs/limitations.md).
