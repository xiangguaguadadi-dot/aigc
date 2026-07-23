#!/usr/bin/env python3
import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


WORKSPACE = Path("/root/scene_recon")
SOURCE = WORKSPACE / "data/room1/source/wechat_room1_20260722.mp4"
BASE = WORKSPACE / "outputs/room1/m3/base"
IMAGES = BASE / "images"
HLOC = BASE / "hloc"
EXPECTED_SOURCE_SHA256 = "2e6964a3270f69a4ac04ae7a0055d3f5418df97d5cd97166428a0ddb2422c74e"
FRAME_RATE_HZ = 2
TEMPORAL_WINDOW_FRAMES = 12
APPEARANCE_TOP_K = 6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def appearance_descriptor(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"cannot read image for pairing: {path}")
    descriptor = cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    descriptor -= descriptor.mean()
    norm = float(np.linalg.norm(descriptor))
    if norm <= 1e-6:
        return np.zeros(descriptor.size, dtype=np.float32)
    return (descriptor / norm).reshape(-1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-after-ffmpeg-cli-failure", action="store_true")
    args = parser.parse_args()

    if sha256(SOURCE) != EXPECTED_SOURCE_SHA256:
        raise SystemExit("source video SHA256 mismatch")
    marker_exists = (BASE / "base_once.json").exists()
    if marker_exists and not args.resume_after_ffmpeg_cli_failure:
        raise SystemExit("base is already initialized; refusing a second preparation")
    if not marker_exists and args.resume_after_ffmpeg_cli_failure:
        raise SystemExit("resume requested without an initialized base")
    if IMAGES.exists() and any(IMAGES.iterdir()):
        raise SystemExit(f"refusing non-empty base images directory: {IMAGES}")
    if HLOC.exists() and any(HLOC.iterdir()):
        raise SystemExit(f"refusing non-empty base HLoc directory: {HLOC}")

    guard_action = "verify" if args.resume_after_ffmpeg_cli_failure else "initialize"
    subprocess.run(
        [str(WORKSPACE / "scripts/m3_room1/base_once_guard.py"), guard_action], check=True
    )
    if not args.resume_after_ffmpeg_cli_failure:
        IMAGES.mkdir(parents=True, exist_ok=False)
        HLOC.mkdir(parents=True, exist_ok=False)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            str(SOURCE),
            "-vf",
            f"fps={FRAME_RATE_HZ}",
            "-q:v",
            "2",
            str(IMAGES / "frame_%06d.jpg"),
        ],
        check=True,
    )

    image_paths = sorted(IMAGES.glob("frame_*.jpg"))
    if len(image_paths) != 93:
        raise SystemExit(f"expected 93 deterministic frames, found {len(image_paths)}")
    frame_records = []
    for index, path in enumerate(image_paths):
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
        if (width, height) != (720, 1280):
            raise SystemExit(f"unexpected frame dimensions for {path.name}: {width}x{height}")
        frame_records.append(
            {
                "index": index,
                "name": path.name,
                "nominal_timestamp_seconds": index / FRAME_RATE_HZ,
                "size_bytes": path.stat().st_size,
                "width": width,
                "height": height,
                "sha256": sha256(path),
            }
        )

    descriptors = np.stack([appearance_descriptor(path) for path in image_paths])
    similarities = descriptors @ descriptors.T
    pairs = set()
    temporal_pair_count = 0
    for first in range(len(image_paths)):
        for second in range(first + 1, min(len(image_paths), first + TEMPORAL_WINDOW_FRAMES + 1)):
            pairs.add((first, second))
            temporal_pair_count += 1
    temporal_pairs = set(pairs)
    for first in range(len(image_paths)):
        candidates = [
            second
            for second in range(len(image_paths))
            if abs(second - first) > TEMPORAL_WINDOW_FRAMES
        ]
        candidates.sort(key=lambda second: (-float(similarities[first, second]), second))
        for second in candidates[:APPEARANCE_TOP_K]:
            pairs.add(tuple(sorted((first, second))))
    ordered_pairs = sorted(pairs)
    pairs_path = HLOC / "pairs.txt"
    pairs_path.write_text(
        "".join(f"{image_paths[first].name} {image_paths[second].name}\n" for first, second in ordered_pairs),
        encoding="ascii",
    )

    generated_at = datetime.now().astimezone().isoformat()
    frame_manifest = {
        "schema_version": 1,
        "generated_at": generated_at,
        "base_id": "room1_shared_base_v1",
        "source_video": str(SOURCE),
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "selection_policy": "ffmpeg fps=2 over full stream with display-matrix autorotation",
        "frame_rate_hz": FRAME_RATE_HZ,
        "frame_count": len(frame_records),
        "output_dimensions": [720, 1280],
        "frames": frame_records,
    }
    pair_manifest = {
        "schema_version": 1,
        "generated_at": generated_at,
        "base_id": "room1_shared_base_v1",
        "frame_count": len(image_paths),
        "temporal_window_frames": TEMPORAL_WINDOW_FRAMES,
        "temporal_window_seconds": TEMPORAL_WINDOW_FRAMES / FRAME_RATE_HZ,
        "appearance_descriptor": "mean-centered normalized 64x64 grayscale",
        "appearance_top_k_per_frame": APPEARANCE_TOP_K,
        "temporal_pair_count": temporal_pair_count,
        "appearance_added_pair_count": len(ordered_pairs) - len(temporal_pairs),
        "total_pair_count": len(ordered_pairs),
        "pairs_sha256": sha256(pairs_path),
    }
    (BASE / "frames_manifest.json").write_text(
        json.dumps(frame_manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    (HLOC / "pairs_manifest.json").write_text(
        json.dumps(pair_manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(json.dumps(pair_manifest, indent=2, sort_keys=True))
    print(f"frames_manifest_sha256={sha256(BASE / 'frames_manifest.json')}")
    print(f"pairs_manifest_sha256={sha256(HLOC / 'pairs_manifest.json')}")


if __name__ == "__main__":
    main()
