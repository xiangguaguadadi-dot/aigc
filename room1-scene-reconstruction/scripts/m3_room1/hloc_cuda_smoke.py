#!/usr/bin/env python3
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path

import h5py
import torch

from hloc import extract_features, match_features
from hloc.utils.parsers import names_to_pair


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_frame(video: Path, timestamp: str, output: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            timestamp,
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"refusing non-empty smoke output: {args.output}")
    image_dir = args.output / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    extract_frame(args.video, "00:00:05.000", image_dir / "smoke_000.jpg")
    extract_frame(args.video, "00:00:05.333", image_dir / "smoke_001.jpg")

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available")
    lhs = torch.arange(4096, device="cuda", dtype=torch.float32).reshape(64, 64)
    cuda_checksum = float((lhs @ lhs.T).sum().item())

    feature_conf = copy.deepcopy(extract_features.confs["superpoint_aachen"])
    feature_path = extract_features.main(
        feature_conf,
        image_dir,
        args.output,
        as_half=True,
        overwrite=True,
    )
    pairs_path = args.output / "pairs.txt"
    pairs_path.write_text("smoke_000.jpg smoke_001.jpg\n", encoding="ascii")
    match_conf = copy.deepcopy(match_features.confs["superglue"])
    match_conf["model"]["weights"] = "indoor"
    matches_path = args.output / "matches-superglue-indoor.h5"
    match_features.main(
        match_conf,
        pairs_path,
        feature_path,
        matches=matches_path,
        overwrite=True,
    )

    with h5py.File(feature_path, "r") as feature_file:
        keypoint_counts = {
            name: int(feature_file[name]["keypoints"].shape[0])
            for name in sorted(feature_file.keys())
        }
    pair_name = names_to_pair("smoke_000.jpg", "smoke_001.jpg")
    with h5py.File(matches_path, "r") as match_file:
        matches = match_file[pair_name]["matches0"][:]
        valid_matches = int((matches >= 0).sum())
    if valid_matches <= 0:
        raise SystemExit("SuperGlue produced no valid matches")

    record = {
        "schema_version": 1,
        "video": str(args.video),
        "frames": ["00:00:05.000", "00:00:05.333"],
        "device": torch.cuda.get_device_name(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_matmul_checksum": cuda_checksum,
        "feature_config": feature_conf,
        "matcher_config": match_conf,
        "keypoint_counts": keypoint_counts,
        "valid_match_count": valid_matches,
        "features_sha256": sha256(feature_path),
        "matches_sha256": sha256(matches_path),
    }
    output_json = args.output / "smoke_result.json"
    output_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(record, indent=2, sort_keys=True))
    print(f"smoke_result_sha256={sha256(output_json)}")


if __name__ == "__main__":
    main()
