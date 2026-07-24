"""Stage 3: Estimate camera poses for object-centric capture.

Primary method: circular trajectory assumption — cameras distributed on
an arc around the object, always pointing inward. This is robust for
textureless objects (cups, furniture, etc.) where SIFT feature matching fails.

Fallback: SIFT + essential matrix for general capture patterns.
"""

import cv2
import numpy as np
from pathlib import Path

from video_to_3d.utils.camera import build_intrinsics, save_cameras, estimate_focal_length
from video_to_3d.utils.validation import check_file_exists


def circular_camera_poses(
    num_frames: int,
    total_angle_deg: float = 270.0,
    radius: float = 1.5,
    height: float = 0.0,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Generate camera poses on a circular arc around the origin.

    Each camera is positioned on a circle at `radius` from origin,
    at `height` above the ground plane, looking toward the origin.

    Args:
        num_frames: Number of camera positions
        total_angle_deg: Total arc angle spanned (degrees)
        radius: Circle radius (in normalized units)
        height: Camera height offset (in normalized units)

    Returns:
        rotations: list of (3, 3) camera→world rotation matrices
        translations: list of (3,) camera positions in world coordinates
    """
    angles = np.linspace(0, np.radians(total_angle_deg), num_frames, endpoint=False)
    rotations = []
    translations = []

    for theta in angles:
        # Camera position on circle
        pos = np.array([
            radius * np.cos(theta),
            radius * np.sin(theta),
            height,
        ], dtype=np.float64)

        # Look-at: camera faces the origin
        forward = -pos / np.linalg.norm(pos)  # camera Z axis in world
        world_up = np.array([0.0, 0.0, 1.0])

        right = np.cross(forward, world_up)
        right_norm = np.linalg.norm(right)
        if right_norm < 1e-8:
            right = np.array([1.0, 0.0, 0.0])
        else:
            right /= right_norm

        up = np.cross(right, forward)
        up /= np.linalg.norm(up)

        # Camera→world rotation matrix (columns are right, up, forward)
        R_cw = np.column_stack([right, up, forward])

        rotations.append(R_cw)
        translations.append(pos)

    return rotations, translations


def _match_features(desc1: np.ndarray, desc2: np.ndarray, ratio_thresh: float = 0.75) -> list[cv2.DMatch]:
    """Match SIFT descriptors with Lowe's ratio test."""
    index_params = dict(algorithm=1, trees=5)
    search_params = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(desc1, desc2, k=2)
    good = []
    for m, n in matches:
        if m.distance < ratio_thresh * n.distance:
            good.append(m)
    return good


def _sift_camera_poses(
    image_paths: list[Path],
    K: np.ndarray,
) -> tuple[list[np.ndarray], list[np.ndarray], list[bool], list[int]]:
    """Estimate poses via sequential SIFT matching.

    Returns: (rotations, translations, success_flags, match_counts)
    """
    sift = cv2.SIFT_create()
    keypoints_list = []
    descriptors_list = []

    for path in image_paths:
        img = cv2.imread(str(path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        kp, desc = sift.detectAndCompute(gray, None)
        keypoints_list.append(kp)
        descriptors_list.append(desc)

    num_images = len(image_paths)
    rotations = [np.eye(3, dtype=np.float64)]
    translations = [np.zeros(3, dtype=np.float64)]
    success_flags = [True]
    match_counts = []

    for i in range(1, num_images):
        desc1, desc2 = descriptors_list[i - 1], descriptors_list[i]
        kp1, kp2 = keypoints_list[i - 1], keypoints_list[i]

        if desc1 is None or desc2 is None or len(desc1) < 8 or len(desc2) < 8:
            rotations.append(rotations[-1].copy())
            translations.append(translations[-1].copy())
            success_flags.append(False)
            match_counts.append(0)
            continue

        matches = _match_features(desc1, desc2)
        match_counts.append(len(matches))

        if len(matches) < 8:
            rotations.append(rotations[-1].copy())
            translations.append(translations[-1].copy())
            success_flags.append(False)
            continue

        src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 2)

        E, inlier_mask = cv2.findEssentialMat(
            src_pts, dst_pts, K, method=cv2.RANSAC, prob=0.999, threshold=1.0
        )

        if E is None or inlier_mask is None or inlier_mask.sum() < 8:
            rotations.append(rotations[-1].copy())
            translations.append(translations[-1].copy())
            success_flags.append(False)
            continue

        _, R_rel, t_rel, _ = cv2.recoverPose(E, src_pts, dst_pts, K, mask=inlier_mask)

        R_prev = rotations[-1]
        t_prev = translations[-1]
        R_i = R_rel @ R_prev
        t_i = t_prev + (R_prev.T @ t_rel).ravel()

        rotations.append(R_i)
        translations.append(t_i)
        success_flags.append(True)

    return rotations, translations, success_flags, match_counts


def run(
    image_paths: list[Path],
    output_dir: Path,
    focal_length_guess: float | None = None,
    method: str = "auto",
    circular_angle: float = 270.0,
) -> dict:
    """Estimate camera poses for a set of ordered images.

    Strategy:
        - "auto" (default): try SIFT first. If average inlier rate is low
          (< 30 matched features per pair), fall back to circular assumption.
        - "circular": assume cameras on an arc around the object.
        - "sift": force SIFT sequential matching.

    Args:
        image_paths: List of paths to raw input images (ordered by capture)
        output_dir: Base output directory
        focal_length_guess: Optional focal length in pixels
        method: "auto" | "circular" | "sift"
        circular_angle: Total arc angle for circular method (degrees)

    Returns:
        dict with cameras dict and summary
    """
    print(f"Estimating camera poses for {len(image_paths)} frames (method={method})...")

    first_img = cv2.imread(str(image_paths[0]))
    if first_img is None:
        raise RuntimeError(f"Cannot read first image: {image_paths[0]}")
    H, W = first_img.shape[:2]

    if focal_length_guess is None or focal_length_guess <= 0:
        focal_length_guess = estimate_focal_length(W, H)
        print(f"  Estimated focal length: {focal_length_guess:.1f} px (from {W}x{H} image)")

    cx, cy = W / 2.0, H / 2.0
    K = build_intrinsics(focal_length_guess, focal_length_guess, cx, cy)

    num_images = len(image_paths)

    # Decide method
    use_circular = (method == "circular")

    if method == "auto":
        # Try SIFT, assess quality
        sift = cv2.SIFT_create()
        total_features = 0
        for path in image_paths:
            img = cv2.imread(str(path))
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            kp = sift.detect(gray, None)
            total_features += len(kp)
        avg_features = total_features / num_images
        print(f"  Avg SIFT features per frame: {avg_features:.0f}")

        if avg_features < 200:
            print(f"  Low feature count ({avg_features:.0f} < 200) — switching to circular assumption")
            use_circular = True
        else:
            print(f"  Sufficient features — using SIFT sequential matching")

    if use_circular:
        rotations, translations = circular_camera_poses(
            num_images, total_angle_deg=circular_angle
        )
        success_flags = [True] * num_images
        method_used = f"circular_{circular_angle}deg"
        print(f"  Circular trajectory: {circular_angle}° arc, {num_images} cameras")
    else:
        rotations, translations, success_flags, match_counts = _sift_camera_poses(
            image_paths, K
        )
        method_used = "sift_sequential"
        for i, mc in enumerate(match_counts):
            print(f"  Frames {i}->{i+1}: {mc} matches")
        print(f"  Successful poses: {sum(success_flags)}/{num_images}")

    # Build output
    frames_data = []
    for i, path in enumerate(image_paths):
        frames_data.append({
            "image": str(path.relative_to(output_dir)),
            "index": i,
            "rotation": rotations[i].tolist(),
            "translation": translations[i].tolist(),
            "success": success_flags[i],
        })

    cameras = {
        "method": method_used,
        "intrinsics": {
            "model": "PINHOLE",
            "width": W,
            "height": H,
            "fx": float(K[0, 0]),
            "fy": float(K[1, 1]),
            "cx": float(K[0, 2]),
            "cy": float(K[1, 2]),
        },
        "num_frames": num_images,
        "frames": frames_data,
    }

    cameras_path = output_dir / "cameras.json"
    save_cameras(cameras, cameras_path)
    print(f"Camera poses saved to: {cameras_path}")

    return {
        "cameras": cameras,
        "cameras_path": cameras_path,
        "summary": {"num_frames": num_images, "successful_poses": sum(success_flags)},
        "rotations": rotations,
        "translations": translations,
    }
