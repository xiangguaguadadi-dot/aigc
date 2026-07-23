#!/usr/bin/env bash
set -euo pipefail

workspace=/root/scene_recon
repo=$workspace/repos/PlanarGS
scene=$workspace/data/planargs_official/classroom
env_dir=$workspace/tools/micromamba-root/envs/planargs
validator=$workspace/scripts/validate_planargs_outputs.py
smoke_model=$workspace/outputs/planargs_official/classroom_smoke_iter1
full_model=$workspace/outputs/planargs_official/classroom_full
mode=${1:-}

if [[ "$mode" != "smoke" && "$mode" != "full" ]]; then
    echo "usage: $0 smoke|full" >&2
    exit 64
fi

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

"$env_dir/bin/python" "$validator" --stage priors --scene "$scene"

if [[ "$mode" == "smoke" ]]; then
    model_path=$smoke_model
    iterations=1
else
    model_path=$full_model
    iterations=30000
fi

if [[ -e "$model_path" ]]; then
    echo "refusing to reuse existing model_path: $model_path" >&2
    exit 73
fi
if [[ "$smoke_model" == "$full_model" ]]; then
    echo "smoke and full model paths must differ" >&2
    exit 70
fi

echo "mode=$mode"
echo "scene=$scene"
echo "model_path=$model_path"
echo "iterations=$iterations"
echo "CONDA_PREFIX=${CONDA_PREFIX}"
echo "CUDA_HOME=${CUDA_HOME}"

cd "$repo"
if [[ "$mode" == "smoke" ]]; then
    exec "$env_dir/bin/python" train.py \
        -s "$scene" \
        -m "$model_path" \
        --iterations 1 \
        --test_iterations 1 \
        --save_iterations 1
fi

exec "$env_dir/bin/python" train.py \
    -s "$scene" \
    -m "$model_path"
