"""Stage 2: Remove background from selected frames using rembg."""

import numpy as np
from pathlib import Path


def run(selected_indices: list[int], frames: list[np.ndarray], output_dir: Path) -> dict:
    """Remove background from selected frames.

    Args:
        selected_indices: List of frame indices
        frames: List of RGB uint8 arrays (H, W, 3)
        output_dir: Base output directory

    Returns:
        dict with foreground paths, mask paths
    """
    from rembg import remove as rembg_remove

    selected_dir = output_dir / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)

    foreground_paths = []
    mask_paths = []

    for idx, frame in zip(selected_indices, frames):
        # rembg expects RGB input, returns RGBA
        result = rembg_remove(frame)  # (H, W, 4), uint8

        # Split into RGB foreground and alpha mask
        rgba = result.astype(np.uint8)
        foreground_rgb = rgba[:, :, :3]
        alpha = rgba[:, :, 3]

        # Save foreground RGBA as PNG
        fg_path = selected_dir / f"foreground_{idx:04d}.png"
        import cv2
        cv2.imwrite(str(fg_path), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
        foreground_paths.append(str(fg_path.relative_to(output_dir)))

        # Save binary mask
        mask_path = selected_dir / f"mask_{idx:04d}.png"
        cv2.imwrite(str(mask_path), alpha)
        mask_paths.append(str(mask_path.relative_to(output_dir)))

        print(f"  Frame {idx}: foreground saved ({alpha.mean()*100:.1f}% foreground)")

    result = {
        "foreground_paths": foreground_paths,
        "mask_paths": mask_paths,
    }

    return result
