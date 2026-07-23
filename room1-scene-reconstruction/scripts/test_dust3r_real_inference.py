#!/usr/bin/env python3
import argparse
import os
import sys

import torch


PLANARGS_ROOT = "/root/scene_recon/repos/PlanarGS"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image-a", required=True)
    parser.add_argument("--image-b", required=True)
    args = parser.parse_args()

    for path in (args.checkpoint, args.image_a, args.image_b):
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise FileNotFoundError(path)

    os.chdir(PLANARGS_ROOT)
    sys.path.insert(0, PLANARGS_ROOT)
    sys.path.insert(0, os.path.join(PLANARGS_ROOT, "submodules", "dust3r"))

    from submodules.dust3r.dust3r.image_pairs import make_pairs
    from submodules.dust3r.dust3r.inference import inference
    from submodules.dust3r.dust3r.model import AsymmetricCroCo3DStereo
    from submodules.dust3r.dust3r.utils.image import load_images

    device = "cuda"
    model = AsymmetricCroCo3DStereo.from_pretrained(args.checkpoint).to(device).eval()
    images = load_images([args.image_a, args.image_b], size=512, verbose=True)
    pairs = make_pairs(images, scene_graph="complete", prefilter=None, symmetrize=True)
    if not pairs:
        raise RuntimeError("DUSt3R produced no image pairs")

    output = inference(pairs[:1], model, device, batch_size=1, verbose=True)
    torch.cuda.synchronize()
    points = output["pred1"]["pts3d"]
    confidence = output["pred1"]["conf"]
    if points.numel() == 0 or confidence.numel() == 0:
        raise RuntimeError("DUSt3R inference returned empty tensors")
    if not torch.isfinite(points).all() or not torch.isfinite(confidence).all():
        raise RuntimeError("DUSt3R inference returned NaN or Inf")

    print(f"points_shape={tuple(points.shape)}")
    print(f"confidence_shape={tuple(confidence.shape)}")
    print(f"confidence_mean={confidence.float().mean().item():.6f}")
    print("dust3r_real_inference=PASS")


if __name__ == "__main__":
    main()
