"""
M1 Real Photo Detection — requires SAM weights.
Run after server-agent finishes downloading SAM.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))

import numpy as np
from PIL import Image
from pipeline.module1_perception.detector import OWLDetector
from pipeline.module1_perception.segmentor import SAMSegmentor
from pipeline.module1_perception.run_detection import _non_max_suppression

# Config
IMAGE = "/root/trellis2-pipeline/room_photo.jpg"
SAM_CKPT = "/root/module1/model_weights/sam_vit_h_4b8939.pth"
PROMPT = "chair . sofa . table . laptop . plant . tv . lamp . curtain . pillow"

print("=" * 60)
print("M1: Real Photo → OWL-ViT + SAM")
print("=" * 60)

# Load image
img = Image.open(IMAGE).convert("RGB")
arr = np.array(img)
print(f"Image: {img.size}")

# Step 1: Detect
t0 = time.time()
detector = OWLDetector(device="cuda", box_threshold=0.08)
boxes, labels, scores = detector.detect(img, PROMPT)
dt = time.time() - t0

# NMS
boxes, labels, scores = _non_max_suppression(boxes, labels, scores, iou_threshold=0.5)
print(f"\n[Step 1] OWL-ViT: {len(boxes)} objects in {dt:.1f}s")
for lbl, sco, box in zip(labels, scores, boxes):
    print(f"  {lbl:10s} conf={sco:.3f}  box={list(box)}")

# Step 2: SAM masks
t0 = time.time()
segmentor = SAMSegmentor(model_type="vit_h", checkpoint=SAM_CKPT)
masks, mask_scores, _ = segmentor.segment_with_boxes(arr, boxes)
dt = time.time() - t0
print(f"\n[Step 2] SAM: {len(masks)} fine masks in {dt:.1f}s")

# Step 3: Per-object image crops
os.makedirs("/root/trellis2-pipeline/m1_output/crops", exist_ok=True)
W, H = img.size
for i, (box, lbl) in enumerate(zip(boxes, labels)):
    x1, y1, x2, y2 = max(0,box[0]), max(0,box[1]), min(W,box[2]), min(H,box[3])
    crop = img.crop((x1, y1, x2, y2))
    crop.save(f"/root/trellis2-pipeline/m1_output/crops/{lbl}_{i:02d}.jpg")

# Step 4: Save results
result = {
    "num_objects": len(boxes),
    "labels": list(labels),
    "boxes": boxes.astype(int).tolist(),
    "scores": [float(s) for s in scores],
    "has_sam_masks": True,
    "num_masks": len(masks),
}
with open("/root/trellis2-pipeline/m1_output/detection.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"\n  Output: /root/trellis2-pipeline/m1_output/")
print(f"  Ready for M2→M3→M4→M5!")
