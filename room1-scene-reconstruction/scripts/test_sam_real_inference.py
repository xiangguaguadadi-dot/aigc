#!/usr/bin/env python3
import argparse
import os
import sys

import cv2
import torch


PLANARGS_ROOT = "/root/scene_recon/repos/PlanarGS"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    for path in (args.checkpoint, args.image):
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise FileNotFoundError(path)

    image = cv2.imread(args.image)
    if image is None:
        raise RuntimeError(f"unreadable image: {args.image}")
    height, width = image.shape[:2]
    box = torch.tensor(
        [[0.2 * width, 0.2 * height, 0.8 * width, 0.8 * height]],
        dtype=torch.float32,
    )

    os.chdir(PLANARGS_ROOT)
    sys.path.insert(0, PLANARGS_ROOT)
    from lp3.run_groundedsam import SAM

    segmenter = SAM("cuda")
    segmenter.load_model(args.checkpoint)
    segmenter.load_image(args.image)
    masks = segmenter.get_segmentation_mask(box)
    torch.cuda.synchronize()
    if masks.shape != (1, 1, height, width) or not torch.isfinite(masks.float()).all():
        raise RuntimeError(f"invalid SAM masks: {tuple(masks.shape)}")
    foreground_ratio = masks.float().mean().item()
    if not 0.0 <= foreground_ratio <= 1.0:
        raise RuntimeError(f"invalid SAM foreground ratio: {foreground_ratio}")

    print(f"mask_shape={tuple(masks.shape)}")
    print(f"foreground_ratio={foreground_ratio:.6f}")
    print("sam_real_inference=PASS")


if __name__ == "__main__":
    main()
