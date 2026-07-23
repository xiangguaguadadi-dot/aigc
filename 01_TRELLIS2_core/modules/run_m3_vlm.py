"""M3: VLM physics analysis on M1 detection results."""
import sys, json, os
import numpy as np
from PIL import Image

sys.path.insert(0, "/root/trellis2-pipeline")
sys.path.insert(0, "/root/trellis2-pipeline/pipeline")

from pipeline.module3_physics.material import VLMPhysicsAnalyzer

# Load scene photo
img = np.array(Image.open("/root/trellis2-pipeline/room_photo.jpg").convert("RGB"))

# Detected objects from M1 (unique labels)
labels = ["laptop", "chair", "table"]

print("M3: VLM analyzing physics from photo...")
vlm = VLMPhysicsAnalyzer()
results = vlm.analyze(img, labels)

for r in results:
    print(f"  {r['name']:10s} | {r['material']:8s} | {r['diameter_cm']:5.0f}cm | {r['mass_kg']:6.2f}kg | rigid={r['rigid']}")

os.makedirs("/root/trellis2-pipeline/m3_output", exist_ok=True)
with open("/root/trellis2-pipeline/m3_output/vlm_physics.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

print("\nSaved: /root/trellis2-pipeline/m3_output/vlm_physics.json")
