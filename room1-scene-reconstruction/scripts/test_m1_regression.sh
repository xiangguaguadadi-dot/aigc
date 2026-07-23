#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^(pre|post)$ ]]; then
    echo "usage: $0 pre|post" >&2
    exit 64
fi

phase=$1
workspace=/root/scene_recon
repo=$workspace/repos/MASt3R-SLAM
lietorch_repo=$workspace/repos/lietorch
env_dir=$workspace/tools/micromamba-root/envs/mast3r-slam
python=$env_dir/bin/python
output_rel=m2_regression/$phase
output_dir=$repo/logs/$output_rel
manifest_dir=$workspace/outputs/m1_regression/$phase

if [[ -e "$output_dir" || -e "$manifest_dir" ]]; then
    echo "refusing to overwrite regression output for phase: $phase" >&2
    exit 73
fi

mkdir -p "$manifest_dir"
export PATH="$env_dir/bin:$PATH"
export LD_LIBRARY_PATH="$env_dir/lib:${LD_LIBRARY_PATH:-}"
export CUDA_HOME="$env_dir"
export TORCH_CUDA_ARCH_LIST=8.0

echo "phase=$phase"
echo "conda_prefix=$env_dir"
echo "cuda_home=$CUDA_HOME"
df -h "$workspace"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader

{
    echo "MASt3R-SLAM_HEAD=$(git -C "$repo" rev-parse HEAD)"
    echo "MASt3R-SLAM_TREE=$(git -C "$repo" rev-parse 'HEAD^{tree}')"
    echo "lietorch_HEAD=$(git -C "$lietorch_repo" rev-parse HEAD)"
    echo "lietorch_TREE=$(git -C "$lietorch_repo" rev-parse 'HEAD^{tree}')"
    sha256sum "$env_dir/conda-meta/history"
    git -C "$repo" submodule status --recursive
    git -C "$lietorch_repo" submodule status --recursive
    "$python" -m pip freeze
} > "$manifest_dir/environment_manifest.txt"

sha256sum \
    "$workspace/checkpoints/mast3r-slam/hf_metric_model/model.safetensors" \
    "$workspace/checkpoints/mast3r-slam/hf_metric_model/config.json" \
    "$workspace/checkpoints/mast3r-slam/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth" \
    "$workspace/checkpoints/mast3r-slam/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_codebook.pkl" \
    > "$manifest_dir/checkpoint_sha256.txt"

"$python" - <<'PY'
import math
import torch
import mast3r_slam_backends
import lietorch
import lietorch_backends
import lietorch_extras

print("torch", torch.__version__)
print("torch_cuda", torch.version.cuda)
print("cuda_available", torch.cuda.is_available())
print("gpu", torch.cuda.get_device_name(0))
assert torch.cuda.is_available()
assert torch.cuda.get_device_name(0) == "NVIDIA A100-PCIE-40GB"
a = torch.randn((1024, 1024), device="cuda")
b = torch.randn((1024, 1024), device="cuda")
c = a @ b
assert bool(torch.isfinite(c).all())
print("cuda_matmul_sum", math.fsum(c.float().cpu().flatten()[:1024].tolist()))
print("extension_imports", "ok")
PY

cd "$repo"
"$python" main.py \
    --dataset datasets/tum/rgbd_dataset_freiburg1_room/ \
    --no-viz \
    --save-as "$output_rel" \
    --config config/eval_calib.yaml

"$python" - "$output_dir" <<'PY'
import pathlib
import sys

import numpy as np
from plyfile import PlyData

output = pathlib.Path(sys.argv[1])
traj = output / "rgbd_dataset_freiburg1_room.txt"
ply = output / "rgbd_dataset_freiburg1_room.ply"
frames = output / "keyframes" / "rgbd_dataset_freiburg1_room"
assert traj.is_file() and traj.stat().st_size > 0
assert ply.is_file() and ply.stat().st_size > 0
values = np.loadtxt(traj)
assert values.ndim == 2 and values.shape[0] > 0 and values.shape[1] == 8
assert np.isfinite(values).all()
data = PlyData.read(ply)
vertices = data["vertex"].data
assert len(vertices) > 0
xyz = np.column_stack((vertices["x"], vertices["y"], vertices["z"]))
assert np.isfinite(xyz).all()
png_count = len(list(frames.glob("*.png")))
assert png_count > 0
print("trajectory_shape", values.shape)
print("point_count", len(vertices))
print("keyframe_png_count", png_count)
print("regression_validation", "passed")
PY

if rg -n -i 'Traceback|CUDA error|out of memory|segmentation fault|illegal memory access' "$output_dir"; then
    echo "fatal pattern found in regression output" >&2
    exit 1
fi

git -C "$repo" status --short
echo "m1_regression_$phase=passed"
