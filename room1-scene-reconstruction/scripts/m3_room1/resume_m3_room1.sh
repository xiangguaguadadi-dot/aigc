#!/usr/bin/env bash
set -o pipefail
cd /root/scene_recon || exit 2

codex exec --dangerously-bypass-approvals-and-sandbox \
  'Resume room1 M3 from the completed shared base. Patched export_metric_variants.py SHA256 2148021025087b80faf4d441a72432b4413b51bc0261448ed8cec6a9997c6234 uses RIGHT_PIXEL 686,1068 and rejects DUSt3R silhouette depth for scale validation. Do not rerun M0-M2 or PlanarGS. Verify log-040 backup, clear only backed active provisional exports, rerun corrected metric export in new log 041 or later, validate scale annotation, then finish steps 6-9: M3A required artifacts, semantic cross-frame review with stable IDs plus masks and numbered sheets, honor only the empty remove_instances.json, derive byte-identical M3B, write manifests and checksums and same-view renders, run Blender headless imports and geometry-scale validation, record commands environment git parameters timing, and write a final report. Preserve all old logs. Never delete by class. Do not generate M4 replacement assets. Diagnose and fix all in-scope issues autonomously.' \
  2>&1 | tee /root/scene_recon/outputs/room1/m3/logs/041_codex_resume_room1_m3.log

status=${PIPESTATUS[0]}
printf 'CODEX_EXIT=%s\n' "$status"
exit "$status"
