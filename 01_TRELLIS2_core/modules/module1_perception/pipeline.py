"""
End-to-End Pipeline: Image → 2D Segments → 3D Labeled Point Cloud.

Module 1: Perception & Instance Segmentation
=============================================
Input:  RGB image(s) + optional depth map
Output: 3D point cloud with per-point object IDs + per-object PLY files

Pipeline:
  1. Grounding DINO → detect objects by text prompt
  2. SAM → refine bounding boxes to pixel masks
  3. 3D Lifter → back-project masks via depth to 3D points
"""

from __future__ import annotations

import os
import json
import time
from typing import List, Tuple, Optional, Dict

import numpy as np
from PIL import Image

from pipeline.module1_perception.config import SegmentationConfig
from pipeline.module1_perception.detector import GroundingDINODetector
from pipeline.module1_perception.segmentor import SAMSegmentor
from pipeline.module1_perception.lifter import MaskLifter3D


class SegmentationPipeline:
    """
    Full Module 1 pipeline.

    Usage:
        config = SegmentationConfig()
        pipeline = SegmentationPipeline(config)
        result = pipeline.run(
            rgb_image=your_image,
            depth_map=optional_depth,
            intrinsic_3x3=camera_intrinsic,
        )
    """

    def __init__(self, config: SegmentationConfig):
        self.config = config
        self.device = config.device

        print("[Module 1] Initializing Perception & Segmentation Pipeline")
        print(f"  Device: {self.device}")

        # 1. Detector (OWL-ViT or GroundingDINO)
        t0 = time.time()
        self.detector = GroundingDINODetector(
            device=config.device,
            box_threshold=config.gdino_box_threshold,
        )
        print(f"  Detector loaded ({time.time()-t0:.1f}s)")

        # 2. Segmentor (SAM — optional, falls back to box-based masks)
        t0 = time.time()
        try:
            self.segmentor = SAMSegmentor(
                model_type=config.sam_model_type,
                checkpoint=config.sam_checkpoint,
                device=config.device,
            )
            self._has_sam = True
            print(f"  SAM loaded ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"  SAM unavailable ({e}), using box-based masks")
            self.segmentor = None
            self._has_sam = False

        # 3. Lifter (initialized per-run with camera intrinsics)
        self.lifter: Optional[MaskLifter3D] = None

    def run(
        self,
        rgb_image: np.ndarray,
        depth_map: Optional[np.ndarray] = None,
        intrinsic_3x3: Optional[np.ndarray] = None,
        text_prompt: Optional[str] = None,
    ) -> dict:
        """
        Run full pipeline on one image.

        Parameters
        ----------
        rgb_image : np.ndarray  shape (H, W, 3), uint8 RGB
        depth_map : np.ndarray or None  shape (H, W) depth in meters
        intrinsic_3x3 : np.ndarray or None  (3,3) camera intrinsic for 3D lifting
        text_prompt : str or None  override config's text prompt

        Returns
        -------
        result : dict with keys:
            - boxes: (N, 4) pixel coords
            - labels: List[str]
            - scores: (N,) detection scores
            - masks: (N, H, W) binary masks
            - objects_3d: dict of obj_id → {points, colors} (only if depth provided)
            - labeled_pcd: (points, colors, labels) fused point cloud
        """
        prompt = text_prompt or self.config.text_prompt
        H, W = rgb_image.shape[:2]

        # ---- Step 1: Detect ----
        print(f"\n[Step 1/3] Grounding DINO detection...")
        print(f"  Prompt: {prompt}")
        t0 = time.time()

        pil_image = Image.fromarray(rgb_image)
        boxes, labels, scores = self.detector.detect(pil_image, prompt)

        print(f"  Found {len(boxes)} objects in {time.time()-t0:.2f}s")
        for lbl, sco in zip(labels, scores):
            print(f"    {lbl}: {sco:.3f}")

        # ---- Step 2: Segment ----
        print(f"\n[Step 2/3] Segmentation...")
        t0 = time.time()

        if self._has_sam and self.segmentor is not None:
            masks, obj_scores, _ = self.segmentor.segment_with_boxes(rgb_image, boxes)
        else:
            # Box-based masks: mask = 1 inside box, 0 outside
            masks = np.zeros((len(boxes), H, W), dtype=bool)
            for i, (x1, y1, x2, y2) in enumerate(boxes):
                masks[i, y1:y2, x1:x2] = True

        # Build unique Object ID per detection
        unique_labels = sorted(set(labels))
        label_to_id = {lbl: i for i, lbl in enumerate(unique_labels)}
        object_ids = np.array([label_to_id[lbl] for lbl in labels], dtype=np.int32)

        print(f"  Generated {len(masks)} masks in {time.time()-t0:.2f}s")

        result = {
            "boxes": boxes,
            "labels": labels,
            "scores": scores,
            "masks": masks,
            "object_ids": object_ids,
            "label_names": {i: lbl for lbl, i in label_to_id.items()},
            "objects_3d": {},
            "labeled_pcd": None,
        }

        # ---- Step 3: 3D Lifting (optional) ----
        if depth_map is not None and intrinsic_3x3 is not None:
            print(f"\n[Step 3/3] 3D mask lifting...")
            t0 = time.time()

            self.lifter = MaskLifter3D(
                intrinsic=intrinsic_3x3,
                depth_scale=self.config.depth_scale,
                min_depth=self.config.min_depth,
                max_depth=self.config.max_depth,
            )

            objects_3d = self.lifter.lift(rgb_image, depth_map, masks, object_ids)
            result["objects_3d"] = objects_3d

            # Build fused labeled point cloud
            pts, cols, lbls = self.lifter.build_labeled_point_cloud(objects_3d)
            result["labeled_pcd"] = (pts, cols, lbls)

            total_pts = sum(len(d["points"]) for d in objects_3d.values())
            print(f"  Lifted {total_pts:,} points across {len(objects_3d)} objects ({time.time()-t0:.2f}s)")
        else:
            print(f"\n[Step 3/3] Skipped — no depth/camera provided (2D only)")

        return result

    def export(
        self,
        result: dict,
        output_dir: Optional[str] = None,
    ) -> Dict[str, str]:
        """Export results: per-object PLY, labeled point cloud, metadata JSON."""
        output_dir = output_dir or self.config.output_dir
        os.makedirs(output_dir, exist_ok=True)
        exported = {}

        label_names = result["label_names"]

        # ---- Per-object PLY ----
        if result["objects_3d"] and self.lifter:
            paths = self.lifter.export_ply(result["objects_3d"], label_names, output_dir)
            exported["per_object_ply"] = paths
            print(f"\n  Exported {len(paths)} per-object PLY files")

        # ---- Fused labeled PLY ----
        if result["labeled_pcd"] is not None:
            pts, cols, lbls = result["labeled_pcd"]
            fused_path = os.path.join(output_dir, "labeled_scene.ply")
            self._write_labeled_ply(fused_path, pts, cols, lbls)
            exported["labeled_scene"] = fused_path
            print(f"  Exported labeled scene: {fused_path} ({len(pts):,} points)")

        # ---- Metadata JSON ----
        meta = {
            "text_prompt": self.config.text_prompt,
            "num_detections": len(result["labels"]),
            "labels": result["labels"],
            "scores": [float(s) for s in result["scores"]],
            "label_mapping": {str(k): v for k, v in label_names.items()},
        }
        meta_path = os.path.join(output_dir, "segmentation_meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        exported["metadata"] = meta_path

        # ---- Visualization (2D overlay) ----
        if self.config.save_visualization:
            vis_path = os.path.join(output_dir, "segmentation_overlay.png")
            self._save_visualization(result, vis_path)
            exported["visualization"] = vis_path

        return exported

    def _write_labeled_ply(
        self, path: str, points: np.ndarray, colors: np.ndarray, labels: np.ndarray
    ):
        """Write PLY with object_id as scalar field."""
        colors = np.clip(colors, 0, 255).astype(np.uint8)
        labels = labels.astype(np.int32)

        with open(path, "w") as f:
            f.write("ply\nformat ascii 1.0\n")
            f.write(f"element vertex {len(points)}\n")
            f.write("property float x\nproperty float y\nproperty float z\n")
            f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
            f.write("property int object_id\n")
            f.write("end_header\n")
            for i in range(len(points)):
                f.write(
                    f"{points[i,0]:.6f} {points[i,1]:.6f} {points[i,2]:.6f} "
                    f"{colors[i,0]} {colors[i,1]} {colors[i,2]} {labels[i]}\n"
                )

    def _save_visualization(self, result: dict, path: str):
        """Save 2D overlay with bounding boxes and masks."""
        # Lazy import to avoid hard dependency
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.patches as patches
        except ImportError:
            print("  (matplotlib not installed, skipping visualization)")
            return

        masks = result["masks"]
        boxes = result["boxes"]
        labels = result["labels"]

        # Use first mask's shape to infer image size
        H, W = masks.shape[1], masks.shape[2]

        fig, ax = plt.subplots(1, 1, figsize=(12, 8))

        # Show combined mask overlay (first mask only for now)
        if len(masks) > 0:
            combined = np.zeros((H, W, 4), dtype=np.float32)
            cmap = plt.cm.tab20
            for i in range(len(masks)):
                color = cmap(i % 20)
                alpha = masks[i].astype(np.float32) * 0.4
                for c in range(3):
                    combined[:, :, c] += color[c] * alpha
            combined[:, :, 3] = np.clip(np.sum([masks[i].astype(np.float32)*0.4 for i in range(len(masks))], axis=0), 0, 1)
            ax.imshow(combined[..., :3])

        # Draw boxes
        for i, (box, lbl) in enumerate(zip(boxes, labels)):
            x1, y1, x2, y2 = box
            rect = patches.Rectangle(
                (x1, y1), x2 - x1, y2 - y1,
                linewidth=2, edgecolor=plt.cm.tab20(i % 20), facecolor="none"
            )
            ax.add_patch(rect)
            ax.text(x1, y1 - 4, lbl, color="white", fontsize=8,
                    bbox=dict(boxstyle="round", facecolor=plt.cm.tab20(i % 20), alpha=0.8))

        ax.set_xlim(0, W)
        ax.set_ylim(H, 0)
        ax.axis("off")
        plt.tight_layout(pad=0)
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Visualization saved: {path}")
