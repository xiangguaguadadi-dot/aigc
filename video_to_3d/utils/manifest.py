"""Asset manifest generation."""

import json
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(path: Path | str) -> str | None:
    """Get current git commit hash, or None if not available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=path,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def generate_manifest(
    output_dir: Path,
    session_id: str,
    input_video: str,
    video_sha256: str,
    glb_path: Path | None,
    parameters: dict,
    warnings: list[str],
    pipeline_log: str | None = None,
    blender_log: str | None = None,
) -> dict:
    """Generate a comprehensive asset manifest.

    Follows the same schema as the existing TripoSR pipeline's asset_manifest.json.
    """
    manifest = {
        # Asset identification
        "asset_id": session_id,
        "pipeline": "video_to_3d",
        "version": "0.1.0",

        # Input
        "input": {
            "video": input_video,
            "sha256": video_sha256,
            "date": datetime.now().isoformat(),
        },

        # Source commit
        "source_commit": _git_commit(output_dir),

        # Parameters used
        "parameters": parameters,

        # Output files
        "outputs": {},

        # Physical status
        "physical": {
            "scale_status": parameters.get("scale_mode", "unscaled"),
            "coordinate_system": "right-handed, +Z up",
            "units": "meters (unscaled)",
            "provenance": "estimated_from_video_depth",
        },

        # Warnings
        "warnings": warnings,

        # Logs
        "logs": {},
    }

    # Record output file hashes
    if glb_path and glb_path.exists():
        manifest["outputs"]["glb"] = {
            "path": str(glb_path.relative_to(output_dir)),
            "sha256": _file_sha256(glb_path),
            "size_bytes": glb_path.stat().st_size,
        }

    preview_png = output_dir / "preview" / "preview.png"
    if preview_png.exists():
        manifest["outputs"]["preview"] = {
            "path": str(preview_png.relative_to(output_dir)),
            "sha256": _file_sha256(preview_png),
        }

    # Log references
    if pipeline_log:
        manifest["logs"]["pipeline"] = pipeline_log
    if blender_log:
        manifest["logs"]["blender"] = blender_log

    return manifest


def save_manifest(manifest: dict, path: Path):
    """Save manifest to JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
