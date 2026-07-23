#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "source this script: source /root/scene_recon/scripts/activate_planargs.sh" >&2
    exit 64
fi

export MAMBA_ROOT_PREFIX=/root/scene_recon/tools/micromamba-root
_planargs_micromamba=/root/scene_recon/tools/bin/micromamba
if [[ ! -x "${_planargs_micromamba}" ]]; then
    echo "micromamba is not executable: ${_planargs_micromamba}" >&2
    return 1
fi

eval "$("${_planargs_micromamba}" shell hook --shell bash)"
micromamba activate /root/scene_recon/tools/micromamba-root/envs/planargs
unset _planargs_micromamba

printf 'CONDA_DEFAULT_ENV=%s\n' "${CONDA_DEFAULT_ENV}"
printf 'CONDA_PREFIX=%s\n' "${CONDA_PREFIX}"
printf 'CUDA_HOME=%s\n' "${CUDA_HOME}"
