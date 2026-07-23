#!/usr/bin/env bash
set -euo pipefail

workspace=/root/scene_recon
repo=$workspace/repos/PlanarGS
env_dir=$workspace/tools/micromamba-root/envs/planargs
model_path=$workspace/outputs/planargs_official/classroom_full
point_cloud=$model_path/point_cloud/iteration_30000/point_cloud.ply
voxel_size=0.02
max_depth=100.0

source "$workspace/scripts/activate_planargs.sh"
[[ "${CONDA_PREFIX:-}" == "$env_dir" ]] || {
    echo "unexpected CONDA_PREFIX: ${CONDA_PREFIX:-unset}" >&2
    exit 70
}

available_gb=$(df --output=avail -BG "$workspace" | tail -n 1 | tr -dc '0-9')
echo "disk_available_gb=$available_gb"
if (( available_gb < 30 )); then
    echo "free disk space is below 30 GB" >&2
    exit 75
fi
if [[ ! -s "$point_cloud" ]]; then
    echo "missing final Gaussian point cloud: $point_cloud" >&2
    exit 66
fi

"$env_dir/bin/python" - <<'PY'
import torch
assert torch.version.cuda == "12.4", torch.version.cuda
assert torch.cuda.is_available()
assert torch.cuda.get_device_name(0) == "NVIDIA A100-PCIE-40GB"
print(f"torch={torch.__version__}")
print(f"torch_cuda={torch.version.cuda}")
print(f"gpu={torch.cuda.get_device_name(0)}")
PY
"$env_dir/bin/nvcc" --version | rg 'release 12\.4,' >/dev/null

echo "model_path=$model_path"
echo "iteration=30000"
echo "voxel_size=$voxel_size"
echo "max_depth=$max_depth"
echo "CONDA_PREFIX=${CONDA_PREFIX}"
echo "CUDA_HOME=${CUDA_HOME}"

cd "$repo"
exec "$env_dir/bin/python" render.py \
    -m "$model_path" \
    --iteration 30000 \
    --voxel_size "$voxel_size" \
    --max_depth "$max_depth"
