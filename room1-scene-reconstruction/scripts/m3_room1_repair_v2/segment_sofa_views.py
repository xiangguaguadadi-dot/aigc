#!/usr/bin/env python3
"""Segment the scale-anchor armchair in a small set of registered views."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image
import torch


ROOT = Path('/root/scene_recon')
REPO = ROOT / 'repos/PlanarGS'
BASE = ROOT / 'outputs/room1/m3_repair_v2/base'
OUT = ROOT / 'outputs/room1/m3_repair_v2/review/sofa_segmentation'
FRAMES = [185, 186, 187, 188, 189, 190, 191, 192]


def main() -> None:
    sys.path.insert(0, str(REPO))
    from lp3.run_groundedsam import GroundingDINO, SAM

    device = 'cuda'
    detector = GroundingDINO(device)
    detector.load_model(str(REPO / 'ckpt/groundingdino_swint_ogc.pth'))
    segmenter = SAM(device)
    segmenter.load_model(str(REPO / 'ckpt/sam_vit_h_4b8939.pth'))
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for number in FRAMES:
        stem = f'frame_{number:06d}'
        path = BASE / 'images' / f'{stem}.jpg'
        rgb = np.asarray(Image.open(path).convert('RGB'))
        height, width = rgb.shape[:2]
        detector.load_image(str(path))
        boxes, phrases = detector.get_detection_output(
            'sofa. armchair. couch. lounge chair.', with_logits=False
        )
        for index in range(boxes.size(0)):
            boxes[index] *= torch.tensor([width, height, width, height])
            boxes[index][:2] -= boxes[index][2:] / 2
            boxes[index][2:] += boxes[index][:2]
        segmenter.load_image(str(path))
        if boxes.size(0):
            masks = segmenter.get_segmentation_mask(boxes).detach().cpu().numpy().astype(bool)
            masks = masks.reshape((len(masks), height, width))
        else:
            masks = np.zeros((0, height, width), dtype=bool)
        np.save(OUT / f'{stem}_masks.npy', masks)

        overlay = rgb.copy()
        colors = [(255, 32, 32), (32, 220, 32), (32, 96, 255), (255, 180, 32)]
        for index, (box, phrase) in enumerate(zip(boxes.cpu().numpy(), phrases)):
            color = colors[index % len(colors)]
            overlay[masks[index]] = (
                0.55 * overlay[masks[index]] + 0.45 * np.asarray(color)
            ).astype(np.uint8)
            x0, y0, x1, y1 = map(int, box)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), color, 3)
            cv2.putText(overlay, str(phrase), (x0, max(20, y0 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        Image.fromarray(overlay).save(OUT / f'{stem}_overlay.jpg', quality=92)
        report[stem] = {
            'boxes_xyxy': boxes.cpu().numpy().tolist(),
            'phrases': [str(item) for item in phrases],
            'mask_pixels': [int(mask.sum()) for mask in masks],
        }
        print(stem, report[stem], flush=True)
    (OUT / 'detections.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
