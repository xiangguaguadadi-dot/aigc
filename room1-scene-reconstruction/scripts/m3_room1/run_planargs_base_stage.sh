#!/usr/bin/env bash
set -euo pipefail

workspace=/root/scene_recon
repo=$workspace/repos/PlanarGS
base=$workspace/outputs/room1/m3/base
model=$base/planargs_model
env_dir=$workspace/tools/micromamba-root/envs/planargs
stage=${1:-}
prompt='wall. floor. door. screen. window. ceiling. table'

if [[ "$stage" != "geom" && "$stage" != "planar" && "$stage" != "train" && "$stage" != "render" ]]; then
    echo "usage: $0 geom|planar|train|render" >&2
    exit 64
fi

source "$workspace/scripts/activate_planargs.sh"
[[ "${CONDA_PREFIX:-}" == "$env_dir" ]] || {
    echo "unexpected CONDA_PREFIX: ${CONDA_PREFIX:-unset}" >&2
    exit 70
}

"$workspace/scripts/m3_room1/check_disk.sh"
"$env_dir/bin/python" "$workspace/scripts/m3_room1/base_once_guard.py" verify
"$env_dir/bin/python" - <<'PY'
import json
from pathlib import Path

acceptance = Path("/root/scene_recon/outputs/room1/m3/review/camera_coverage/camera_coverage_acceptance.json")
payload = json.loads(acceptance.read_text(encoding="ascii"))
assert payload["base_id"] == "room1_shared_base_v1"
assert payload["accepted_for_shared_planargs_base"] is True
assert payload["registered_image_count"] == 57
assert payload["sofa_anchor"]["registered"] is True
print("camera_coverage_gate=PASS")
PY

"$env_dir/bin/python" - <<'PY'
import os
import torch

assert torch.__version__.startswith("2.4.1"), torch.__version__
assert torch.version.cuda == "12.4", torch.version.cuda
assert torch.cuda.is_available()
assert torch.cuda.get_device_name(0) == "NVIDIA A100-PCIE-40GB"
assert os.environ.get("CUDA_HOME") == "/root/scene_recon/tools/micromamba-root/envs/planargs"
print(f"torch={torch.__version__}")
print(f"torch_cuda={torch.version.cuda}")
print(f"gpu={torch.cuda.get_device_name(0)}")
print(f"compute_capability={torch.cuda.get_device_capability(0)}")
PY
"$env_dir/bin/nvcc" --version | grep -q 'release 12\.4,'
echo "nvcc_cuda=12.4"

echo "stage=$stage"
echo "base=$base"
echo "base_id=room1_shared_base_v1"
echo "model=$model"
echo "prompt=$prompt"
echo "planargs_commit=$(git -C "$repo" rev-parse HEAD)"
echo "planargs_tree=$(git -C "$repo" rev-parse 'HEAD^{tree}')"

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
cd "$repo"

case "$stage" in
    geom)
        [[ ! -e "$base/geomprior" ]] || {
            echo "refusing duplicate geometric-prior run: $base/geomprior" >&2
            exit 73
        }
        echo "group_size=30"
        exec "$env_dir/bin/python" run_geomprior.py -s "$base" --group_size 30
        ;;
    planar)
        [[ -s "$base/geomprior/depth_weights.json" ]] || {
            echo "geometric priors are not validated or complete" >&2
            exit 66
        }
        [[ ! -e "$base/planarprior" ]] || {
            echo "refusing duplicate LP3 run: $base/planarprior" >&2
            exit 73
        }
        for required in \
            "$repo/bert-base-uncased/config.json" \
            "$repo/bert-base-uncased/model.safetensors" \
            "$repo/bert-base-uncased/tokenizer.json" \
            "$repo/bert-base-uncased/tokenizer_config.json" \
            "$repo/bert-base-uncased/vocab.txt" \
            "$repo/ckpt/groundingdino_swint_ogc.pth" \
            "$repo/ckpt/sam_vit_h_4b8939.pth"; do
            [[ -s "$required" ]] || {
                echo "missing offline LP3 input: $required" >&2
                exit 66
            }
        done
        exec "$env_dir/bin/python" run_lp3.py -s "$base" -t "$prompt" --vis
        ;;
    train)
        [[ -s "$base/geomprior/depth_weights.json" ]] || exit 66
        [[ -d "$base/planarprior/mask" ]] || exit 66
        [[ ! -e "$model" ]] || {
            echo "refusing duplicate shared-base training: $model" >&2
            exit 73
        }
        echo "iterations=30000"
        exec "$env_dir/bin/python" train.py \
            -s "$base" \
            -m "$model" \
            --iterations 30000 \
            --test_iterations 7000 30000 \
            --save_iterations 7000 30000
        ;;
    render)
        point_cloud=$model/point_cloud/iteration_30000/point_cloud.ply
        [[ -s "$point_cloud" ]] || {
            echo "missing final shared-base Gaussian point cloud: $point_cloud" >&2
            exit 66
        }
        [[ ! -e "$model/mesh" && ! -e "$model/train/ours_30000" ]] || {
            echo "refusing duplicate render or TSDF run for $model" >&2
            exit 73
        }
        echo "iteration=30000"
        echo "voxel_size=0.02"
        echo "max_depth=100.0"
        exec "$env_dir/bin/python" render.py \
            -m "$model" \
            --iteration 30000 \
            --voxel_size 0.02 \
            --max_depth 100.0
        ;;
esac
