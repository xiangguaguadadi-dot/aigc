#!/usr/bin/env python
"""CLI entry point for the Video-to-3D Pipeline.

Usage:
    python -m video_to_3d.scripts.run_video_to_3d --video path/to/video.mp4
    python -m video_to_3d.scripts.run_video_to_3d --video path/to/video.mp4 --frames 10
    python -m video_to_3d.scripts.run_video_to_3d --video path/to/video.mp4 --camera circular
    python -m video_to_3d.scripts.run_video_to_3d --video path/to/video.mp4 --depth-model base
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Video-to-3D Mesh Pipeline — Transform monocular video into 3D assets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --video object_video.mp4
  %(prog)s --video object_video.mp4 --camera circular --frames 10
  %(prog)s --video object_video.mp4 --depth-model base --frames 8
  %(prog)s --video object_video.mp4 --asset-id my_object_001
        """,
    )

    parser.add_argument(
        "--video", "-i", required=True,
        help="Path to input video file (.mp4, .mov, .webm, .avi)",
    )
    parser.add_argument(
        "--frames", "-n", type=int, default=8,
        help="Number of keyframes to extract (default: 8)",
    )
    parser.add_argument(
        "--asset-id", "-a", default=None,
        help="Asset/session ID (auto-generated if not provided)",
    )
    parser.add_argument(
        "--output-root", "-o", default="outputs",
        help="Root output directory (default: outputs/)",
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Overwrite existing output directory",
    )
    parser.add_argument(
        "--camera", choices=["auto", "circular", "sift"], default="auto",
        help="Camera estimation method (default: auto — auto-detect)",
    )
    parser.add_argument(
        "--circular-angle", type=float, default=270.0,
        help="Total arc angle for circular camera (default: 270 degrees)",
    )
    parser.add_argument(
        "--depth-model",
        choices=["small", "base", "large"], default="small",
        help="Depth model size (default: small, 35M params)",
    )
    parser.add_argument(
        "--target-faces", type=int, default=50000,
        help="Target face count for output mesh (default: 50000)",
    )
    parser.add_argument(
        "--compare-triposr", action="store_true",
        help="Also run TripoSR on the best frame for comparison",
    )
    parser.add_argument(
        "--triposr-source", default=None,
        help="Path to TripoSR source code (required if --compare-triposr is set)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Validate video path
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"ERROR: Video file not found: {video_path}")
        sys.exit(1)

    if args.compare_triposr and args.triposr_source is None:
        print("ERROR: --compare-triposr requires --triposr-source")
        sys.exit(1)

    # Map depth model name to HuggingFace ID
    depth_model_map = {
        "small": "depth-anything/Depth-Anything-V2-Small-hf",
        "base": "depth-anything/Depth-Anything-V2-Base-hf",
        "large": "depth-anything/Depth-Anything-V2-Large-hf",
    }

    # Override config values
    import video_to_3d.config as cfg
    cfg.DEFAULT_NUM_FRAMES = args.frames
    cfg.CAMERA_METHOD = args.camera
    cfg.CIRCULAR_ANGLE = args.circular_angle
    cfg.DEPTH_MODEL = depth_model_map[args.depth_model]
    cfg.TARGET_FACE_COUNT = args.target_faces

    depth_model_name = {"small": "Small(35M)", "base": "Base(97M)", "large": "Large(335M)"}[args.depth_model]

    print(f"Video-to-3D Pipeline")
    print(f"  Input:  {video_path}")
    print(f"  Frames: {args.frames}")
    print(f"  Camera: {args.camera}" + (f" ({args.circular_angle}° arc)" if args.camera == "circular" else ""))
    print(f"  Depth:  {depth_model_name}")
    print(f"  Output: {Path(args.output_root) / (args.asset_id or '<auto>')}")
    print()

    try:
        from video_to_3d.pipeline import run_pipeline

        result = run_pipeline(
            video_path=str(video_path.absolute()),
            session_id=args.asset_id,
            output_root=args.output_root,
            num_frames=args.frames,
            force=args.force,
            compare_triposr=args.compare_triposr,
            triposr_source=args.triposr_source,
        )
        print(f"\nSuccess! Output: {result['output_dir']}")
        if result.get("glb_path"):
            print(f"  GLB: {result['glb_path']}")
        print(f"  Manifest: {result['manifest_path']}")

    except FileExistsError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Pipeline failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
