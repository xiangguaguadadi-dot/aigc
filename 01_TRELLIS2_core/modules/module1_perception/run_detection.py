"""
M1: Real image → OWL-ViT detection → labeled objects.

Usage:
  python run_detection.py --image photo.jpg --prompt "chair . table . sofa . cup"
"""

import sys, os
# Add project root (trellis2-pipeline/) to path
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import argparse, json, time
import numpy as np
from PIL import Image

from pipeline.module1_perception.config import SegmentationConfig
from pipeline.module1_perception.detector import OWLDetector
from pipeline.module1_perception.segmentor import SAMSegmentor


def _non_max_suppression(boxes, labels, scores, iou_threshold=0.5):
    """Remove duplicate detections with IoU > threshold. Keeps highest score."""
    if len(boxes) == 0:
        return boxes, labels, scores

    def _iou(a, b):
        x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
        x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
        inter = max(0, x2-x1) * max(0, y2-y1)
        area_a = (a[2]-a[0]) * (a[3]-a[1])
        area_b = (b[2]-b[0]) * (b[3]-b[1])
        return inter / (area_a + area_b - inter + 1e-6)

    order = np.argsort(scores)[::-1]
    keep = []
    suppressed = np.zeros(len(boxes), dtype=bool)
    for i in order:
        if suppressed[i]:
            continue
        keep.append(i)
        for j in order:
            if j == i or suppressed[j]:
                continue
            if labels[i] == labels[j] and _iou(boxes[i], boxes[j]) > iou_threshold:
                suppressed[j] = True

    return boxes[keep], [labels[k] for k in keep], scores[keep]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", default="chair . table . sofa . cup . laptop . plant . tv . lamp")
    parser.add_argument("--threshold", type=float, default=0.08)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    img = Image.open(args.image).convert("RGB")
    arr = np.array(img)
    print(f"Image: {img.size}")

    # ---- Step 1: OWL-ViT Detection ----
    print(f"\n[M1] Detecting: {args.prompt}")
    t0 = time.time()
    detector = OWLDetector(device="cuda", box_threshold=args.threshold)
    boxes, labels, scores = detector.detect(img, args.prompt)
    dt = time.time() - t0
    print(f"  Found {len(boxes)} objects in {dt:.1f}s")

    if len(boxes) == 0:
        print("  No objects detected! Try lower --threshold")
        return

    # ---- NMS deduplication ----
    boxes, labels, scores = _non_max_suppression(boxes, labels, scores, iou_threshold=0.5)

    # Show results
    unique_labels = sorted(set(labels))
    print(f"\n  After NMS: {len(boxes)} objects, {len(unique_labels)} categories: {unique_labels}")
    for lbl, sco, box in zip(labels, scores, boxes):
        print(f"    {lbl:12s} conf={sco:.3f}  box=[{box[0]},{box[1]},{box[2]},{box[3]}]")

    # ---- Step 2: SAM fine masks (if available) ----
    masks = None
    try:
        from pipeline.module1_perception.config import SegmentationConfig
        cfg = SegmentationConfig()
        cfg.sam_checkpoint = "/root/module1/model_weights/sam_vit_h_4b8939.pth"
        segmentor = SAMSegmentor(model_type="vit_h", checkpoint=cfg.sam_checkpoint)
        masks, mask_scores, _ = segmentor.segment_with_boxes(arr, boxes)
        print(f"\n  SAM: Generated {len(masks)} fine masks")
    except Exception as e:
        print(f"\n  SAM: unavailable ({e}), using box masks")
        masks = None

    # ---- Save results ----
    output = args.output or os.path.splitext(args.image)[0] + "_m1.json"
    result = {
        "image": args.image,
        "prompt": args.prompt,
        "num_objects": len(boxes),
        "labels": labels,
        "scores": [float(s) for s in scores],
        "boxes": boxes.astype(int).tolist(),
        "categories": unique_labels,
    }
    with open(output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n  Saved: {output}")


if __name__ == "__main__":
    main()
