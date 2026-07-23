#!/usr/bin/env bash
set -euo pipefail

workspace=/root/scene_recon
repo=$workspace/repos/PlanarGS
scene=$workspace/data/planargs_official/classroom
validator=$workspace/scripts/validate_planargs_outputs.py
env_dir=$workspace/tools/micromamba-root/envs/planargs
phase=${1:-all}
group_size=${2:-40}
prompt='wall. floor. door. screen. window. ceiling. table'

if [[ "$phase" != "geom" && "$phase" != "planar" && "$phase" != "all" ]]; then
    echo "usage: $0 [geom|planar|all] [40|30|25]" >&2
    exit 64
fi
if [[ "$group_size" != "40" && "$group_size" != "30" && "$group_size" != "25" ]]; then
    echo "group_size must be 40, 30, or 25" >&2
    exit 64
fi

source "$workspace/scripts/activate_planargs.sh"
[[ "${CONDA_PREFIX:-}" == "$env_dir" ]] || {
    echo "unexpected CONDA_PREFIX: ${CONDA_PREFIX:-unset}" >&2
    exit 70
}

check_disk() {
    local available_gb
    available_gb=$(df --output=avail -BG "$workspace" | tail -n 1 | tr -dc '0-9')
    echo "disk_available_gb=$available_gb"
    if (( available_gb < 30 )); then
        echo "free disk space is below 30 GB" >&2
        exit 75
    fi
}

check_cuda_gate() {
    "$env_dir/bin/python" - <<'PY'
import os
import torch

assert torch.version.cuda == "12.4", torch.version.cuda
assert torch.cuda.is_available()
assert torch.cuda.get_device_name(0) == "NVIDIA A100-PCIE-40GB"
assert os.environ.get("CUDA_HOME") == "/root/scene_recon/tools/micromamba-root/envs/planargs"
print(f"torch={torch.__version__}")
print(f"torch_cuda={torch.version.cuda}")
print(f"gpu={torch.cuda.get_device_name(0)}")
print(f"compute_capability={torch.cuda.get_device_capability(0)}")
PY
    "$env_dir/bin/nvcc" --version | rg 'release 12\.4,' >/dev/null
    echo "nvcc_cuda=12.4"
}

echo "phase=$phase"
echo "scene=$scene"
echo "group_size=$group_size"
echo "prompt=$prompt"
echo "CONDA_PREFIX=${CONDA_PREFIX}"
echo "CUDA_HOME=${CUDA_HOME}"
check_disk
check_cuda_gate
"$env_dir/bin/python" "$validator" --stage scene --scene "$scene"

cd "$repo"
if [[ "$phase" == "geom" || "$phase" == "all" ]]; then
    check_disk
    "$env_dir/bin/python" run_geomprior.py -s "$scene" --group_size "$group_size"
fi

if [[ "$phase" == "planar" || "$phase" == "all" ]]; then
    check_disk
    "$env_dir/bin/python" "$validator" --stage priors --scene "$scene" --skip-planar
    "$env_dir/bin/python" run_lp3.py -s "$scene" -t "$prompt"
fi
