"""Default configuration and environment detection."""

import os
from pathlib import Path

# ── Blender ─────────────────────────────────────────────
BLENDER_BIN = os.environ.get(
    "BLENDER_BIN",
    r"C:\Users\NewUser\Applications\blender-4.5.11-windows-x64\blender.exe",
)

# ── Output ───────────────────────────────────────────────
OUTPUT_ROOT = Path("outputs")

# ── Stage defaults ───────────────────────────────────────
DEFAULT_NUM_FRAMES = 8       # Number of keyframes to select
MIN_FRAME_COVERAGE = 180     # Minimum angular coverage (degrees)
SHARPNESS_THRESHOLD = 50     # Minimum Laplacian variance for a frame to be kept

# Depth model — available variants:
#   depth-anything/Depth-Anything-V2-Small-hf  (35M params, ~2-3s/frame on CPU)
#   depth-anything/Depth-Anything-V2-Base-hf   (97M params, ~5-8s/frame on CPU)
#   depth-anything/Depth-Anything-V2-Large-hf  (335M params, ~15-20s/frame on CPU)
DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"

# Camera estimation
CAMERA_METHOD = "auto"       # auto | circular | sift
CIRCULAR_ANGLE = 270.0       # Total arc for circular method (degrees)

# Reconstruction
TSDF_VOXEL_SIZE = 0.008      # TSDF voxel size (relative to scene extent)
TARGET_FACE_COUNT = 50000    # Decimate to this many faces
POISSON_DEPTH = 9            # Poisson reconstruction depth (higher = more detail, 9-10)

SCALE_MODE = "unit_box"      # unit_box | user_reference | metric_depth

# ── Directories ──────────────────────────────────────────
SELECTED_DIR = "selected"
DEPTH_DIR = "depth"
POINTCLOUD_DIR = "pointcloud"
MESH_DIR = "mesh"
BLENDER_DIR = "blender"
EXPORT_DIR = "export"
PREVIEW_DIR = "preview"
LOGS_DIR = "logs"
TRIPOSR_DIR = "triposr_compare"
