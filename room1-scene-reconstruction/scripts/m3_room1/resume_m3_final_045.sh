#!/usr/bin/env bash
set -o pipefail
cd /root/scene_recon || exit 2

codex exec --dangerously-bypass-approvals-and-sandbox \
  'Continue and finish room1 M3 from logs 041 through 044. The prior Codex turn was interrupted only because it was idle waiting for the API; no child job was active. Do not rerun M0-M2, PlanarGS, scale export, or SAM review. Correct sofa scale 0.24019853045911085 m per unit and log 042 instance review are complete. Log 043 detected a glTF Y-up import-axis mismatch; log 044 safely backed the affected artifacts and normalized both full and asset-ready GLBs by storing canonical Blender coordinates as glTF x,z,-y, without changing PLY, scale, or cameras. First verify this state. Then run fresh post-fix Blender headless import and same-camera render passes for full and asset_ready in new immutable logs, require their imported vertex bounds to agree with canonical PLY within float tolerance, visually inspect renders, and require byte-identical geometry and pixel-identical renders because remove_instances.json is empty. Make the rerun recipe reproducible by patching the primary exporter or explicitly chaining the normalization script, with an audit record. Finish all required scene manifests, checksums.sha256 files, removal and geometry-difference reports, comparison renders, environment command parameter timing Git-status records, and final M3 report. Validate every required artifact and checksum. Preserve all old logs and backups. Never delete by class and do not create M4 assets. Diagnose and repair any in-scope failure autonomously.' \
  2>&1 | tee /root/scene_recon/logs/m3_room1/codex_final_resume_stdout.log

status=${PIPESTATUS[0]}
printf 'CODEX_EXIT=%s\n' "$status"
exit "$status"
