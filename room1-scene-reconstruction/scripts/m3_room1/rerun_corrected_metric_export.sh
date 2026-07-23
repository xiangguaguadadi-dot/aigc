#!/usr/bin/env bash
set -euo pipefail

workspace=/root/scene_recon
backup_root=$workspace/outputs/room1/m3/review/backups/log_040_scale_export_20260722_211855_+0800
exporter=$workspace/scripts/m3_room1/export_metric_variants.py
expected_exporter_sha=2148021025087b80faf4d441a72432b4413b51bc0261448ed8cec6a9997c6234

cd "$workspace"

actual_exporter_sha=$(sha256sum "$exporter" | awk '{print $1}')
if [[ "$actual_exporter_sha" != "$expected_exporter_sha" ]]; then
    echo "patched exporter SHA256 mismatch: $actual_exporter_sha" >&2
    exit 65
fi

provisional_paths=(
    outputs/room1/m3/full/camera_poses.json
    outputs/room1/m3/full/coordinate_transform.json
    outputs/room1/m3/full/scale_calibration.json
    outputs/room1/m3/full/static_collision_full.glb
    outputs/room1/m3/full/static_scene_full.glb
    outputs/room1/m3/full/static_scene_full.ply
    outputs/room1/m3/asset_ready/camera_poses.json
    outputs/room1/m3/asset_ready/coordinate_transform.json
    outputs/room1/m3/asset_ready/removal_report.json
    outputs/room1/m3/asset_ready/scale_calibration.json
    outputs/room1/m3/asset_ready/static_collision_asset_ready.glb
    outputs/room1/m3/asset_ready/static_scene_asset_ready.glb
    outputs/room1/m3/asset_ready/static_scene_asset_ready.ply
    outputs/room1/m3/review/scale/camera_poses.json
    outputs/room1/m3/review/scale/coordinate_transform.json
    outputs/room1/m3/review/scale/scale_calibration.json
    outputs/room1/m3/review/scale/sofa_scale_endpoints.png
    outputs/room1/m3/review/validation/geometry_export_metrics.json
)

for relative_path in "${provisional_paths[@]}"; do
    active_path=$workspace/$relative_path
    backup_path=$backup_root/$relative_path
    [[ -f "$active_path" ]] || { echo "missing active provisional file: $active_path" >&2; exit 66; }
    [[ -f "$backup_path" ]] || { echo "missing backup file: $backup_path" >&2; exit 66; }
    cmp --silent "$active_path" "$backup_path" || {
        echo "active provisional file differs from backup: $relative_path" >&2
        exit 67
    }
    printf 'backup_verified=%s sha256=%s\n' "$relative_path" "$(sha256sum "$active_path" | awk '{print $1}')"
done

for relative_path in "${provisional_paths[@]}"; do
    rm -- "$workspace/$relative_path"
    printf 'cleared_backed_provisional=%s\n' "$relative_path"
done

exec "$workspace/tools/micromamba-root/envs/planargs/bin/python" "$exporter"
