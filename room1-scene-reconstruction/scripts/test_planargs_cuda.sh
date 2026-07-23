#!/usr/bin/env bash
set -euo pipefail

source /root/scene_recon/scripts/activate_planargs.sh

expected_prefix=/root/scene_recon/tools/micromamba-root/envs/planargs
[[ "${CONDA_PREFIX}" == "${expected_prefix}" ]]
[[ "${CUDA_HOME}" == "${expected_prefix}" ]]
[[ "$(command -v python)" == "${expected_prefix}/bin/python" ]]
[[ "$(command -v nvcc)" == "${expected_prefix}/bin/nvcc" ]]

nvcc_output=$(nvcc --version)
printf '%s\n' "${nvcc_output}"
if ! grep -Eq 'release 12\.4([,[:space:]]|$)' <<<"${nvcc_output}"; then
    echo "CUDA version gate failed: environment nvcc is not release 12.4" >&2
    exit 1
fi

printf 'gcc=%s\n' "$(gcc --version | head -n 1)"
printf 'CUDA_HOME=%s\n' "${CUDA_HOME}"
printf 'PATH=%s\n' "${PATH}"
printf 'LD_LIBRARY_PATH=%s\n' "${LD_LIBRARY_PATH}"

python - <<'PY'
import math
import os
import sys

import torch

expected_prefix = "/root/scene_recon/tools/micromamba-root/envs/planargs"
assert sys.prefix == expected_prefix, (sys.prefix, expected_prefix)
assert torch.__version__ == "2.4.1", torch.__version__
assert torch.version.cuda == "12.4", torch.version.cuda
assert torch.cuda.is_available(), "CUDA is unavailable"
assert torch.cuda.get_device_name(0) == "NVIDIA A100-PCIE-40GB"
assert torch.cuda.get_device_capability(0) == (8, 0)
assert os.environ.get("CUDA_HOME") == expected_prefix

torch.manual_seed(124)
left = torch.randn((1024, 1024), device="cuda", dtype=torch.float32)
right = torch.randn((1024, 1024), device="cuda", dtype=torch.float32)
product = left @ right
torch.cuda.synchronize()
checksum = product.abs().sum().item()
assert product.device.type == "cuda"
assert product.shape == (1024, 1024)
assert math.isfinite(checksum) and checksum > 0

print(f"python={sys.version.split()[0]}")
print(f"torch={torch.__version__}")
print(f"torch_cuda={torch.version.cuda}")
print(f"cuda_available={torch.cuda.is_available()}")
print(f"gpu={torch.cuda.get_device_name(0)}")
print(f"compute_capability={torch.cuda.get_device_capability(0)}")
print(f"cuda_matmul_checksum={checksum:.6f}")
print("cuda_12_4_version_gate=PASS")
PY
