"""Optional: Compare with TripoSR result from the best single frame."""

import cv2
import json
import numpy as np
from pathlib import Path


def run(
    best_frame_rgb: np.ndarray,
    frame_index: int,
    output_dir: Path,
    triposr_source: str | None = None,
) -> dict:
    """Run TripoSR on the best single frame and compare.

    This is an independent comparison path, NOT integrated into the
    main fusion pipeline. Provides a side-by-side quality report.

    Args:
        best_frame_rgb: (H, W, 3) RGB image of the best frame
        frame_index: Index of the selected best frame
        output_dir: Base output directory
        triposr_source: Path to TripoSR source directory (optional)

    Returns:
        dict with comparison result
    """
    compare_dir = output_dir / "triposr_compare"
    compare_dir.mkdir(parents=True, exist_ok=True)

    # Save the best frame
    frame_path = compare_dir / "best_frame.png"
    cv2.imwrite(str(frame_path), cv2.cvtColor(best_frame_rgb, cv2.COLOR_RGB2BGR))

    if triposr_source is None:
        print("TripoSR comparison: skipping (no source path provided)")
        return {"status": "skipped", "reason": "no_triposr_source"}

    comparison_report = {
        "frame_index": frame_index,
        "status": "triposr_available",
        "note": "TripoSR comparison not yet implemented in this version",
    }

    with open(compare_dir / "comparison_report.json", "w") as f:
        json.dump(comparison_report, f, indent=2)

    return comparison_report
