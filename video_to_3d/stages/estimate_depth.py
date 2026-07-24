"""Stage 4: Depth estimation using DepthAnythingV2."""

import numpy as np
from pathlib import Path

from video_to_3d.utils.io import write_depth_npy, save_depth_visualization
from video_to_3d.utils.validation import check_depth_map


def run(
    image_paths: list[Path],
    mask_paths: list[Path],
    output_dir: Path,
    model_name: str = "depth-anything/Depth-Anything-V2-Small-hf",
    device: str = "cpu",
) -> dict:
    """Estimate depth maps for selected frames.

    Args:
        image_paths: Paths to foreground RGB images
        mask_paths: Paths to binary mask images
        output_dir: Base output directory
        model_name: HuggingFace model name for depth estimation
        device: Device for inference ('cpu' or 'cuda')

    Returns:
        dict with depth file paths and summary
    """
    import cv2
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    depth_dir = output_dir / "depth"
    depth_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading depth model: {model_name}")
    processor = AutoImageProcessor.from_pretrained(model_name)
    model = AutoModelForDepthEstimation.from_pretrained(model_name)
    model.eval()

    if device == "cuda" and torch.cuda.is_available():
        model.to("cuda")
        print("  Using CUDA")
    else:
        print("  Using CPU")

    depth_paths = []
    viz_paths = []
    depth_stats = []

    for i, (img_path, mask_path) in enumerate(zip(image_paths, mask_paths)):
        # Load image
        img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"Cannot read image: {img_path}")
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Load mask
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)

        print(f"  Estimating depth for frame {i} ({img_path.name})...")

        # Run inference
        inputs = processor(images=img_rgb, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
            depth = outputs.predicted_depth.squeeze().cpu().numpy()

        # Resize back to original image size
        original_h, original_w = img_rgb.shape[:2]
        depth = cv2.resize(depth, (original_w, original_h), interpolation=cv2.INTER_LINEAR)

        # Apply mask: zero out background
        if mask is not None:
            mask_binary = (mask > 0).astype(np.float32)
            depth = depth * mask_binary

        # Validate
        check_depth_map(depth, f"Depth frame {i}")

        # Save
        depth_path = depth_dir / f"depth_{i:04d}.npy"
        viz_path = depth_dir / f"depth_{i:04d}_viz.png"
        write_depth_npy(depth_path, depth)
        save_depth_visualization(viz_path, depth)
        depth_paths.append(str(depth_path.relative_to(output_dir)))
        viz_paths.append(str(viz_path.relative_to(output_dir)))

        valid = depth[depth > 0]
        stats = {
            "min": float(valid.min()) if len(valid) > 0 else 0,
            "max": float(valid.max()) if len(valid) > 0 else 0,
            "mean": float(valid.mean()) if len(valid) > 0 else 0,
            "valid_pixels": int((depth > 0).sum()),
        }
        depth_stats.append(stats)
        print(f"    Depth range: {stats['min']:.3f} - {stats['max']:.3f}, "
              f"mean: {stats['mean']:.3f}")

    result = {
        "depth_paths": depth_paths,
        "viz_paths": viz_paths,
        "depth_stats": depth_stats,
        "num_frames": len(image_paths),
    }

    return result
