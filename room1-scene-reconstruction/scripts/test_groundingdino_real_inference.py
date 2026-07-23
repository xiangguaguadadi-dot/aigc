#!/usr/bin/env python3
import argparse
import os
import sys

import torch


PLANARGS_ROOT = "/root/scene_recon/repos/PlanarGS"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", default="wall. floor. door. screen. window. ceiling. table")
    args = parser.parse_args()

    for path in (args.checkpoint, args.image):
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise FileNotFoundError(path)

    os.chdir(PLANARGS_ROOT)
    sys.path.insert(0, PLANARGS_ROOT)
    from lp3.run_groundedsam import GroundingDINO

    detector = GroundingDINO("cuda")
    detector.load_model(args.checkpoint)
    detector.load_image(args.image)
    boxes, phrases = detector.get_detection_output(args.prompt, with_logits=True)
    torch.cuda.synchronize()
    if boxes.ndim != 2 or boxes.shape[-1] != 4 or not torch.isfinite(boxes).all():
        raise RuntimeError(f"invalid GroundingDINO boxes: {tuple(boxes.shape)}")

    print(f"boxes_shape={tuple(boxes.shape)}")
    print(f"phrase_count={len(phrases)}")
    print("groundingdino_real_inference=PASS")


if __name__ == "__main__":
    main()
