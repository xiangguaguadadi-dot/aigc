"""Coverage estimation for keyframe selection."""

import numpy as np


def estimate_angular_coverage(frame_count: int, stride: int = 1) -> float:
    """Estimate angular coverage from frame indices.

    For a typical object-centric video (phone circling an object),
    this uses frame sequence position as a proxy for angle.
    Assumes ~1 degree per frame at 30fps circling in ~12s.

    Args:
        frame_count: Number of frames in the sequence
        stride: Frame sampling stride

    Returns:
        Estimated coverage in degrees
    """
    # Crude estimate: at 30 fps, 360-degree circle in ~12 seconds = 360 frames
    degrees_per_frame = 360.0 / 360  # ~1 degree/frame at typical speed
    return min(360.0, (frame_count - 1) * stride * degrees_per_frame)


def check_coverage(frame_count: int, min_degrees: float = 180.0) -> tuple[bool, float]:
    """Check if a frame sequence has sufficient angular coverage.

    Args:
        frame_count: Number of frames
        min_degrees: Minimum required coverage

    Returns:
        (sufficient, estimated_degrees)
    """
    estimated = estimate_angular_coverage(frame_count)
    return estimated >= min_degrees, estimated


def select_uniform_frames(total_frames: int, num_select: int) -> np.ndarray:
    """Select evenly spaced frame indices covering the sequence.

    Args:
        total_frames: Total available frames
        num_select: Number to select

    Returns:
        Array of selected indices
    """
    if total_frames <= num_select:
        return np.arange(total_frames)
    indices = np.linspace(0, total_frames - 1, num_select, dtype=int)
    return indices
