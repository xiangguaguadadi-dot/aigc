# Reproducibility

## Recorded Environment

- GPU: NVIDIA A100-PCIE-40GB
- GPU memory: 40,960 MiB
- Driver: 570.211.01
- Scene workspace used by the run: `/root/scene_recon`
- PlanarGS environment: Python 3.10
- MASt3R-SLAM environment: Python 3.11

Exact Python snapshots are stored under `environment/`.

## Stage Order

1. Select strict video keyframes with
   `scripts/m3_room1_repair_v2/select_keyframes_v2.py`.
2. Extract/match HLoc features with
   `scripts/m3_room1_repair_v2/run_fast_hloc_v2.py`.
3. Build the COLMAP main model with
   `scripts/m3_room1_repair_v2/run_mapper_v3.py`.
4. Generate DUSt3R/MASt3R priors with
   `run_geomprior_parallel.py` or `run_geomprior_split_group.py`.
5. Align the registered depth subset and repair scale-invariant confidence weights with
   `repair_depth_weights.py`.
6. Run the PlanarGS prior and 30,000-iteration optimization stages.
7. Render depth and fuse the TSDF mesh.
8. Segment the sofa views and estimate its multi-view 3D cluster with
   `segment_sofa_views.py` and `measure_sofa_cloud.py`.
9. Export M3A with `export_m3a_full.py`; use the Blender helpers to produce valid GLB
   files, previews and import validation.

## Path Assumptions

These files are an execution snapshot, not a packaged Python library. Scripts may contain:

- `/root/scene_recon` workspace paths;
- `outputs/room1/m3_repair_v2` run paths;
- micromamba environment paths;
- PlanarGS and HLoc checkout paths.

Preserve the original layout for exact reruns, or replace these constants with local
configuration values before running elsewhere. Passwords, API keys, SSH hosts and raw
download credentials are not included.

## Important Checkpoints

Checkpoint binaries are intentionally excluded. Retrieve them from their official sources,
verify their upstream license, and compare hashes before inference. Do not commit them to
Git.

## Model Selection Rule

The 211-camera main COLMAP model was retained. A 29-camera secondary model was not merged
because it shared only one image with the main model; forcing a similarity alignment under
that condition would risk scene tearing.
