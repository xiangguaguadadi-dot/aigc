"""Stage 1: Extract keyframes from video and assess quality."""

import cv2
import numpy as np
import json
from pathlib import Path

from video_to_3d.quality.sharpness import laplacian_variance
from video_to_3d.quality.coverage import select_uniform_frames, check_coverage
from video_to_3d.utils.io import write_depth_npy
from video_to_3d.utils.validation import check_file_exists


def run(
    video_path: str,
    output_dir: Path,
    num_frames: int = 6,
    sharpness_threshold: float = 50.0,
    min_coverage: float = 180.0,
) -> dict:
    """Extract and select keyframes from video.

    Args:
        video_path: Path to input video file
        output_dir: Base output directory
        num_frames: Number of keyframes to select
        sharpness_threshold: Minimum Laplacian variance to keep a frame
        min_coverage: Minimum angular coverage required

    Returns:
        dict with paths, quality scores, and selected indices
    """
    # Create output directories
    frames_dir = output_dir / "frames"
    selected_dir = output_dir / "selected"
    frames_dir.mkdir(parents=True, exist_ok=True)
    selected_dir.mkdir(parents=True, exist_ok=True)

    # Open video
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if total_frames <= 0:
        raise RuntimeError(f"Video has no frames: {video_path}")

    print(f"Video: {total_frames} frames, {fps:.1f} fps, {width}x{height}")

    # Read all frames
    raw_frames = []
    raw_indices = []
    for i in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        raw_frames.append(rgb)
        raw_indices.append(i)

    cap.release()
    total_read = len(raw_frames)
    print(f"Read {total_read} frames")

    # Score sharpness
    scores = [laplacian_variance(f) for f in raw_frames]
    quality_info = {
        "total_frames": total_read,
        "fps": fps,
        "width": width,
        "height": height,
        "sharpness_scores": scores,
    }

    # Select frames by uniform sampling first
    uniform_idx = select_uniform_frames(total_read, num_frames * 2)
    candidates = [(i, raw_frames[i], scores[i]) for i in uniform_idx]

    # Refine by sharpness among candidates
    candidates.sort(key=lambda x: x[2], reverse=True)
    selected = candidates[:num_frames]
    selected.sort(key=lambda x: x[0])  # restore temporal order

    selected_indices = [s[0] for s in selected]
    selected_frames = [s[1] for s in selected]
    selected_scores = [s[2] for s in selected]

    print(f"Selected {len(selected_indices)} frames: indices {selected_indices}")
    print(f"Sharpness scores: {[f'{s:.1f}' for s in selected_scores]}")

    # Check coverage
    coverage_ok, estimated_deg = check_coverage(
        len(raw_indices), min_coverage
    )
    quality_info["estimated_coverage_degrees"] = estimated_deg
    quality_info["coverage_sufficient"] = coverage_ok

    if not coverage_ok:
        print(f"WARNING: Estimated coverage {estimated_deg:.0f}° < {min_coverage}° required")

    # Save selected frames
    frame_paths = []
    for i, (idx, frame) in enumerate(zip(selected_indices, selected_frames)):
        # Save raw frame
        raw_path = selected_dir / f"raw_{idx:04d}.png"
        cv2.imwrite(str(raw_path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        frame_paths.append({
            "index": idx,
            "raw_path": str(raw_path.relative_to(output_dir)),
            "sharpness": scores[idx],
        })

    # Save quality scores JSON
    quality_path = selected_dir / "quality_scores.json"
    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(quality_info, f, indent=2)

    result = {
        "selected_indices": selected_indices,
        "selected_frames": selected_frames,  # RGB arrays for downstream stages
        "frame_paths": frame_paths,
        "quality_info": quality_info,
        "quality_path": quality_path,
        "selected_dir": selected_dir,
    }

    return result
