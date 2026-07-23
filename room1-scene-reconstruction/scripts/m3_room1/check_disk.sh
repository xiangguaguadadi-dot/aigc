#!/usr/bin/env bash
set -euo pipefail

workspace=/root/scene_recon
available_gb=$(df --output=avail -BG "$workspace" | tail -n 1 | tr -dc '0-9')
echo "disk_available_gb=$available_gb"
echo "disk_threshold_gb=30"
if (( available_gb < 30 )); then
    echo "free disk space is below 30 GB" >&2
    exit 75
fi
