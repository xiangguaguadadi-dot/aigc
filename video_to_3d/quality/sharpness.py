"""Sharpness scoring using Laplacian variance."""

import cv2
import numpy as np


def laplacian_variance(image: np.ndarray) -> float:
    """Compute Laplacian variance as a blur/sharpness metric.

    Higher values = sharper image. Lower values = more blurry.

    Args:
        image: (H, W) or (H, W, C) uint8 image

    Returns:
        Variance of the Laplacian response
    """
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def score_frames(frames: list[np.ndarray]) -> list[float]:
    """Score a list of frames by sharpness.

    Args:
        frames: List of RGB uint8 arrays

    Returns:
        List of sharpness scores in same order
    """
    return [laplacian_variance(f) for f in frames]


def select_sharpest(frames: list[np.ndarray], scores: list[float], n: int) -> list[int]:
    """Select indices of the N sharpest frames.

    Args:
        frames: List of frames
        scores: Sharpness scores
        n: Number to select

    Returns:
        Sorted list of selected indices in original order
    """
    if len(frames) <= n:
        return list(range(len(frames)))

    # Get top N indices sorted by score descending
    top_indices = np.argsort(scores)[-n:]
    # Return in original order
    return sorted(top_indices.tolist())
