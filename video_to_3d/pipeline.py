"""Main pipeline orchestrator.

Coordinates all stages in order, with checkpoint tracking for resumption.
"""

import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from datetime import datetime

from video_to_3d.config import (
    OUTPUT_ROOT,
    DEFAULT_NUM_FRAMES,
    MIN_FRAME_COVERAGE,
    SHARPNESS_THRESHOLD,
    DEPTH_MODEL,
    TSDF_VOXEL_SIZE,
    TARGET_FACE_COUNT,
    SCALE_MODE,
    BLENDER_BIN,
)

logger = logging.getLogger("video_to_3d")


class PipelineContext:
    """Holds pipeline state across all stages."""

    def __init__(self, session_id: str, output_dir: Path, params: dict):
        self.session_id = session_id
        self.output_dir = output_dir
        self.params = params
        self.stage_times = {}
        self.warnings = []
        self.results = {}

        # Create directory structure
        for subdir in ["frames", "selected", "depth", "pointcloud", "mesh",
                       "blender", "export", "preview", "logs"]:
            (output_dir / subdir).mkdir(parents=True, exist_ok=True)

        # Setup logging
        log_path = output_dir / "logs" / "pipeline.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info(f"Pipeline started: {session_id}")
        logger.info(f"Parameters: {params}")

    def run_stage(self, name: str, stage_fn, **kwargs):
        """Run a pipeline stage with timing and checkpointing."""
        checkpoint = self.output_dir / "stage_checkpoints.json"
        completed = self._load_checkpoints(checkpoint)

        if name in completed:
            logger.info(f"Stage '{name}' already completed, skipping")
            print(f"[SKIP] Stage '{name}' already done")
            return completed[name]

        logger.info(f"Starting stage: {name}")
        print(f"\n{'='*60}")
        print(f"Stage: {name}")
        print(f"{'='*60}")

        t0 = time.time()
        try:
            result = stage_fn(**kwargs)
            elapsed = time.time() - t0
            self.stage_times[name] = elapsed
            self.results[name] = result
            logger.info(f"Stage '{name}' completed in {elapsed:.1f}s")
            print(f"[OK] '{name}' finished in {elapsed:.1f}s")

            # Save checkpoint
            completed[name] = {"status": "ok", "elapsed": elapsed}
            self._save_checkpoints(checkpoint, completed)

            return result

        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"Stage '{name}' FAILED after {elapsed:.1f}s: {e}", exc_info=True)
            print(f"[FAIL] Stage '{name}' failed: {e}")
            completed[name] = {"status": "failed", "error": str(e)}
            self._save_checkpoints(checkpoint, completed)
            raise

    @staticmethod
    def _load_checkpoints(path: Path) -> dict:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    @staticmethod
    def _save_checkpoints(path: Path, data: dict):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def run_pipeline(
    video_path: str,
    session_id: str | None = None,
    output_root: str | Path = OUTPUT_ROOT,
    num_frames: int = DEFAULT_NUM_FRAMES,
    force: bool = False,
    compare_triposr: bool = False,
    triposr_source: str | None = None,
) -> dict:
    """Run the full video-to-3D pipeline.

    Args:
        video_path: Path to input video file
        session_id: Optional asset ID (auto-generated if None)
        output_root: Root output directory
        num_frames: Number of keyframes to extract
        force: Overwrite existing output
        compare_triposr: Also run TripoSR on the best frame for comparison
        triposr_source: Path to TripoSR source code (required if compare_triposr=True)

    Returns:
        Summary dict with all results and manifest path
    """
    # Auto-generate session ID
    video_path_obj = Path(video_path)
    if session_id is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"video_{timestamp}"

    output_dir = Path(output_root) / session_id

    if output_dir.exists() and not force:
        raise FileExistsError(
            f"Output directory already exists: {output_dir}\n"
            f"Use --force to overwrite."
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    # Compute video hash
    logger.info(f"Computing SHA-256 of input video...")
    sha256_hash = hashlib.sha256()
    with open(video_path_obj, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256_hash.update(chunk)
    video_sha256 = sha256_hash.hexdigest()

    params = {
        "num_frames": num_frames,
        "scale_mode": SCALE_MODE,
        "depth_model": DEPTH_MODEL,
        "target_faces": TARGET_FACE_COUNT,
        "compare_triposr": compare_triposr,
    }

    ctx = PipelineContext(session_id, output_dir, params)

    # ── Stage 1: Frame Extraction + Quality Assessment ──
    from video_to_3d.stages.extract_frames import run as stage1
    stage1_result = ctx.run_stage(
        "1_extract_frames",
        stage1,
        video_path=str(video_path_obj.absolute()),
        output_dir=output_dir,
        num_frames=num_frames,
        sharpness_threshold=SHARPNESS_THRESHOLD,
        min_coverage=MIN_FRAME_COVERAGE,
    )

    selected_indices = stage1_result["selected_indices"]
    selected_frames = stage1_result["selected_frames"]
    frame_paths = stage1_result["frame_paths"]
    selected_dir = stage1_result["selected_dir"]

    # Build paths for selected frames
    raw_frame_paths = [selected_dir / f"raw_{idx:04d}.png" for idx in selected_indices]

    # ── Stage 2: Background Removal ──
    from video_to_3d.stages.remove_bg import run as stage2
    stage2_result = ctx.run_stage(
        "2_remove_background",
        stage2,
        selected_indices=selected_indices,
        frames=selected_frames,
        output_dir=output_dir,
    )

    foreground_paths = [output_dir / p for p in stage2_result["foreground_paths"]]
    mask_paths = [output_dir / p for p in stage2_result["mask_paths"]]

    # ── Stage 3: Camera Estimation ──
    from video_to_3d.stages.estimate_camera import run as stage3
    from video_to_3d.config import CAMERA_METHOD, CIRCULAR_ANGLE
    stage3_result = ctx.run_stage(
        "3_estimate_camera",
        stage3,
        image_paths=raw_frame_paths,
        output_dir=output_dir,
        method=CAMERA_METHOD,
        circular_angle=CIRCULAR_ANGLE,
    )

    cameras_path = stage3_result["cameras_path"]

    # ── Stage 4: Depth Estimation ──
    from video_to_3d.stages.estimate_depth import run as stage4
    stage4_result = ctx.run_stage(
        "4_estimate_depth",
        stage4,
        image_paths=foreground_paths,
        mask_paths=mask_paths,
        output_dir=output_dir,
        model_name=DEPTH_MODEL,
    )

    depth_paths = [output_dir / p for p in stage4_result["depth_paths"]]

    # ── Stage 5: Point Cloud Fusion ──
    from video_to_3d.stages.fuse_pointcloud import run as stage5
    stage5_result = ctx.run_stage(
        "5_fuse_pointcloud",
        stage5,
        depth_paths=depth_paths,
        mask_paths=mask_paths,
        foreground_paths=foreground_paths,
        cameras_path=cameras_path,
        output_dir=output_dir,
    )

    point_cloud = stage5_result["point_cloud"]

    # ── Stage 6: Surface Reconstruction ──
    from video_to_3d.stages.reconstruct_mesh import run as stage6
    stage6_result = ctx.run_stage(
        "6_reconstruct_mesh",
        stage6,
        point_cloud=point_cloud,
        output_dir=output_dir,
        target_face_count=TARGET_FACE_COUNT,
    )

    mesh_path = output_dir / stage6_result["mesh_path"]
    mesh_info = stage6_result["mesh_info"]

    # ── Stage 7: Blender Normalization ──
    from video_to_3d.blender.normalize import run_blender
    try:
        ctx.run_stage(
            "7_blender_normalize",
            lambda: run_blender(str(mesh_path.absolute()), str(output_dir.absolute()), BLENDER_BIN),
        )
        blender_success = True
    except Exception as e:
        ctx.warnings.append(f"Blender normalization failed: {e}")
        logger.warning(f"Blender normalization skipped: {e}")
        print(f"[WARN] Blender normalization: {e}")
        blender_success = False

    # ── Stage 8: Asset Manifest ──
    from video_to_3d.utils.manifest import generate_manifest, save_manifest

    glb_path = output_dir / "export" / f"{Path(stage6_result['mesh_path']).stem}.glb"
    if not glb_path.exists():
        glb_path = None

    manifest = generate_manifest(
        output_dir=output_dir,
        session_id=session_id,
        input_video=str(video_path_obj),
        video_sha256=video_sha256,
        glb_path=glb_path,
        parameters=params,
        warnings=ctx.warnings,
        pipeline_log=str(output_dir / "logs" / "pipeline.log"),
        blender_log=str(output_dir / "logs" / "blender.log") if blender_success else None,
    )

    # Add mesh info
    manifest["mesh"] = mesh_info
    manifest["stage_times"] = ctx.stage_times
    manifest["stages_completed"] = list(ctx.stage_times.keys())

    manifest_path = output_dir / "asset_manifest.json"
    save_manifest(manifest, manifest_path)
    logger.info(f"Manifest saved: {manifest_path}")

    # ── Optional: TripoSR Comparison ──
    if compare_triposr:
        from video_to_3d.stages.triposr_compare import run as run_triposr
        best_idx = selected_indices[0]  # first selected frame
        best_frame = selected_frames[0]
        ctx.run_stage(
            "triposr_compare",
            run_triposr,
            best_frame_rgb=best_frame,
            frame_index=best_idx,
            output_dir=output_dir,
            triposr_source=triposr_source,
        )

    # Summary
    print(f"\n{'='*60}")
    print(f"Pipeline complete: {session_id}")
    print(f"  Output: {output_dir}")
    print(f"  GLB: {glb_path}")
    print(f"  Faces: {mesh_info['faces']}, Watertight: {mesh_info['is_watertight']}")
    print(f"  Manifest: {manifest_path}")
    print(f"{'='*60}")

    return {
        "session_id": session_id,
        "output_dir": output_dir,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "glb_path": glb_path,
    }
