#!/usr/bin/env python3
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from segment_anything import SamPredictor, sam_model_registry


ROOT = Path("/root/scene_recon")
M3 = ROOT / "outputs/room1/m3"
BASE_IMAGES = M3 / "base/images"
REVIEW = M3 / "review/instances"
MASKS = REVIEW / "masks"
NUMBERED = REVIEW / "numbered_reviews"
CHECKPOINT = ROOT / "checkpoints/planargs/sam_vit_h_4b8939.pth"

INSTANCES = [
    {"id": "R1-I001", "number": 1, "name": "left sofa", "label": "fixed_furniture", "removal_eligible_by_label": False},
    {"id": "R1-I002", "number": 2, "name": "round-base work table", "label": "fixed_furniture", "removal_eligible_by_label": False},
    {"id": "R1-I003", "number": 3, "name": "wheeled sit-stand desk", "label": "fixed_furniture", "removal_eligible_by_label": False},
    {"id": "R1-I004", "number": 4, "name": "foreground desk monitor", "label": "movable_rigid", "removal_eligible_by_label": True},
    {"id": "R1-I005", "number": 5, "name": "wall-mounted display", "label": "fixed_furniture", "removal_eligible_by_label": False},
    {"id": "R1-I006", "number": 6, "name": "striped sofa cushion", "label": "movable_rigid", "removal_eligible_by_label": True},
    {"id": "R1-I007", "number": 7, "name": "glass partition and door", "label": "structural_static", "removal_eligible_by_label": False},
    {"id": "R1-I008", "number": 8, "name": "clear water bottle", "label": "movable_rigid", "removal_eligible_by_label": True},
    {"id": "R1-I009", "number": 9, "name": "ceiling security camera", "label": "fixed_furniture", "removal_eligible_by_label": False},
    {"id": "R1-I010", "number": 10, "name": "rear desk monitor", "label": "movable_rigid", "removal_eligible_by_label": True},
    {"id": "R1-I011", "number": 11, "name": "desktop cable and small-item cluster", "label": "uncertain", "removal_eligible_by_label": True},
    {"id": "R1-I012", "number": 12, "name": "black office chair", "label": "articulated", "removal_eligible_by_label": True},
]

# Boxes are [x0, y0, x1, y1] in the immutable 720x1280 selected keyframes.
OBSERVATIONS = {
    "frame_000005.jpg": {
        "R1-I001": [30, 700, 719, 1279],
        "R1-I005": [650, 390, 719, 790],
        "R1-I006": [285, 780, 475, 1110],
    },
    "frame_000020.jpg": {
        "R1-I002": [0, 960, 540, 1279],
        "R1-I004": [0, 830, 175, 1160],
        "R1-I007": [255, 80, 719, 1190],
        "R1-I009": [205, 130, 285, 245],
    },
    "frame_000030.jpg": {
        "R1-I002": [0, 370, 719, 1279],
        "R1-I004": [270, 55, 660, 475],
        "R1-I008": [335, 395, 430, 655],
        "R1-I010": [150, 70, 310, 305],
        "R1-I011": [0, 320, 310, 625],
    },
    "frame_000050.jpg": {
        "R1-I007": [280, 0, 719, 1120],
    },
    "frame_000060.jpg": {
        "R1-I003": [0, 0, 560, 610],
        "R1-I012": [445, 180, 719, 735],
    },
    "frame_000078.jpg": {
        "R1-I001": [0, 680, 719, 1279],
        "R1-I005": [575, 380, 719, 850],
        "R1-I006": [255, 815, 490, 1279],
    },
    "frame_000092.jpg": {
        "R1-I002": [0, 935, 719, 1279],
        "R1-I004": [245, 770, 545, 1125],
        "R1-I005": [0, 690, 375, 1070],
        "R1-I009": [530, 290, 610, 405],
    },
}

COLORS = [
    (230, 57, 70), (29, 185, 84), (32, 121, 219), (245, 166, 35),
    (153, 82, 204), (0, 166, 166), (215, 79, 144), (105, 105, 105),
    (120, 84, 38), (0, 95, 160), (180, 120, 0), (70, 150, 90),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    authority = json.loads((M3 / "remove_instances.json").read_text(encoding="ascii"))
    if authority.get("remove_instances") != []:
        raise AssertionError("instance review finalization expects the authorized empty removal list")
    for path in (MASKS, NUMBERED, M3 / "removable_candidates.json", M3 / "removable_candidates.csv", REVIEW / "instance_review.json", REVIEW / "numbered_instance_review_sheet.jpg"):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite instance review output: {path}")
    if not torch.cuda.is_available():
        raise RuntimeError("SAM review requires CUDA")

    MASKS.mkdir(parents=True)
    NUMBERED.mkdir(parents=True)
    model = sam_model_registry["vit_h"](checkpoint=str(CHECKPOINT))
    model.to(device="cuda")
    predictor = SamPredictor(model)
    by_id = {item["id"]: item for item in INSTANCES}
    font = ImageFont.load_default()
    observation_records = []
    numbered_paths = []

    for frame_name, prompts in OBSERVATIONS.items():
        image_bgr = cv2.imread(str(BASE_IMAGES / frame_name), cv2.IMREAD_COLOR)
        if image_bgr is None or image_bgr.shape[:2] != (1280, 720):
            raise AssertionError(f"invalid selected keyframe: {frame_name}")
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        predictor.set_image(image_rgb)
        overlay = image_rgb.astype(np.float32)

        frame_records = []
        for instance_id, box in prompts.items():
            masks, scores, _ = predictor.predict(
                point_coords=None,
                point_labels=None,
                box=np.asarray(box, dtype=np.float32),
                multimask_output=True,
            )
            selected = int(np.argmax(scores))
            mask = masks[selected].astype(bool)
            ratio = float(mask.mean())
            if not 0.0001 < ratio < 0.90:
                raise AssertionError(f"implausible mask ratio for {frame_name} {instance_id}: {ratio}")
            instance = by_id[instance_id]
            color = np.asarray(COLORS[instance["number"] - 1], dtype=np.float32)
            overlay[mask] = 0.55 * overlay[mask] + 0.45 * color
            mask_dir = MASKS / instance_id
            mask_dir.mkdir(exist_ok=True)
            mask_path = mask_dir / f"{Path(frame_name).stem}.png"
            if not cv2.imwrite(str(mask_path), mask.astype(np.uint8) * 255):
                raise RuntimeError(f"failed to write {mask_path}")
            record = {
                "instance_id": instance_id,
                "frame": frame_name,
                "prompt_box_xyxy": box,
                "sam_score": float(scores[selected]),
                "foreground_ratio": ratio,
                "mask": str(mask_path),
                "mask_sha256": sha256(mask_path),
            }
            frame_records.append(record)
            observation_records.append(record)

        review_image = Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(review_image)
        for record in frame_records:
            instance = by_id[record["instance_id"]]
            box = record["prompt_box_xyxy"]
            color = COLORS[instance["number"] - 1]
            draw.rectangle(box, outline=color, width=4)
            label = f'{instance["number"]:02d} {instance["id"]} {instance["name"]}'
            text_y = max(0, box[1] - 18)
            draw.rectangle((box[0], text_y, min(719, box[0] + len(label) * 7), text_y + 16), fill=(0, 0, 0))
            draw.text((box[0] + 2, text_y + 2), label, fill=color, font=font)
        numbered_path = NUMBERED / f"{Path(frame_name).stem}_numbered.jpg"
        review_image.save(numbered_path, quality=94)
        numbered_paths.append(numbered_path)

    thumbs = []
    for path in numbered_paths:
        with Image.open(path) as image:
            thumb = image.copy()
        thumb.thumbnail((360, 640), Image.Resampling.LANCZOS)
        thumbs.append((path, thumb))
    sheet = Image.new("RGB", (360 * 4, 680 * 2), "white")
    sheet_draw = ImageDraw.Draw(sheet)
    for index, (path, thumb) in enumerate(thumbs):
        x = (index % 4) * 360
        y = (index // 4) * 680
        sheet.paste(thumb, (x, y + 22))
        sheet_draw.text((x + 4, y + 4), path.stem, fill="black", font=font)
    sheet_path = REVIEW / "numbered_instance_review_sheet.jpg"
    sheet.save(sheet_path, quality=94)

    observations_by_id = {item["id"]: [] for item in INSTANCES}
    for record in observation_records:
        observations_by_id[record["instance_id"]].append(record["frame"])
    candidates = []
    catalog = []
    for instance in INSTANCES:
        entry = {
            **instance,
            "observed_frames": sorted(observations_by_id[instance["id"]]),
            "cross_frame_association": "manual spatial/appearance association over immutable selected keyframes",
            "authorized_for_removal": False,
            "removal_authority": str(M3 / "remove_instances.json"),
        }
        catalog.append(entry)
        if instance["removal_eligible_by_label"]:
            candidates.append(entry)

    candidates_payload = {
        "schema_version": 1,
        "scene_id": "room1",
        "base_id": "room1_shared_base_v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "policy": "class labels are review metadata only and never authorize removal",
        "authorized_remove_instances": [],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    candidates_json = M3 / "removable_candidates.json"
    candidates_json.write_text(json.dumps(candidates_payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    candidates_csv = M3 / "removable_candidates.csv"
    with candidates_csv.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "number", "name", "label", "observed_frames", "removal_eligible_by_label", "authorized_for_removal"])
        writer.writeheader()
        for item in candidates:
            writer.writerow({**{key: item[key] for key in writer.fieldnames if key != "observed_frames"}, "observed_frames": ";".join(item["observed_frames"])})

    review_payload = {
        "schema_version": 1,
        "scene_id": "room1",
        "base_id": "room1_shared_base_v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "method": "SAM ViT-H box-prompt segmentation followed by manual cross-frame stable-ID association",
        "checkpoint": str(CHECKPOINT),
        "checkpoint_sha256": sha256(CHECKPOINT),
        "device": torch.cuda.get_device_name(0),
        "selected_keyframes": sorted(OBSERVATIONS),
        "stable_instance_count": len(INSTANCES),
        "mask_count": len(observation_records),
        "instances": catalog,
        "observations": observation_records,
        "numbered_review_images": [str(path) for path in numbered_paths],
        "numbered_sheet": str(sheet_path),
        "numbered_sheet_sha256": sha256(sheet_path),
        "removal_policy": "no masks were used for geometry exclusion; empty authority retains every instance",
    }
    review_json = REVIEW / "instance_review.json"
    review_json.write_text(json.dumps(review_payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps({
        "stable_instance_count": len(INSTANCES),
        "mask_count": len(observation_records),
        "candidate_count": len(candidates),
        "authorized_remove_instances": [],
        "numbered_sheet_sha256": sha256(sheet_path),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
