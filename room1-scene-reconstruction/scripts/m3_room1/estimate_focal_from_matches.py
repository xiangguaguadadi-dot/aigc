#!/usr/bin/env python3
import json
from pathlib import Path

import cv2
import h5py
import numpy as np

from hloc.utils.parsers import names_to_pair, names_to_pair_old


BASE = Path("/root/scene_recon/outputs/room1/m3/base")
FEATURES = BASE / "hloc/feats-superpoint-n4096-r1024.h5"
MATCHES = BASE / "hloc/matches-superglue-indoor.h5"
PAIRS = BASE / "hloc/pairs.txt"
OUTPUT = BASE / "hloc/focal_grid_evaluation.json"


def match_group(handle: h5py.File, name0: str, name1: str):
    for key in (names_to_pair(name0, name1), names_to_pair_old(name0, name1)):
        if key in handle:
            return handle[key]
    return None


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing existing focal evaluation: {OUTPUT}")
    candidates = list(range(500, 1401, 25))
    pair_records = []
    with h5py.File(FEATURES, "r") as feature_file, h5py.File(MATCHES, "r") as match_file:
        for line in PAIRS.read_text(encoding="ascii").splitlines():
            name0, name1 = line.split()
            index0 = int(name0[6:12])
            index1 = int(name1[6:12])
            separation = abs(index1 - index0)
            if not 6 <= separation <= 12:
                continue
            group = match_group(match_file, name0, name1)
            if group is None:
                continue
            matches = group["matches0"][:]
            valid = np.flatnonzero(matches >= 0)
            if len(valid) < 80:
                continue
            keypoints0 = feature_file[name0]["keypoints"][:].astype(np.float64)[valid]
            keypoints1 = feature_file[name1]["keypoints"][:].astype(np.float64)[matches[valid]]
            pair_records.append((name0, name1, keypoints0, keypoints1))
    pair_records.sort(key=lambda item: (item[0], item[1]))
    if len(pair_records) < 10:
        raise SystemExit(f"insufficient focal-evaluation pairs: {len(pair_records)}")
    pair_records = pair_records[:30]

    evaluations = []
    for focal in candidates:
        camera_matrix = np.array(
            [[focal, 0.0, 360.0], [0.0, focal, 640.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        inlier_counts = []
        cheirality_counts = []
        for _, _, keypoints0, keypoints1 in pair_records:
            cv2.setRNGSeed(0)
            essential, mask = cv2.findEssentialMat(
                keypoints0,
                keypoints1,
                camera_matrix,
                method=cv2.RANSAC,
                prob=0.999,
                threshold=1.5,
            )
            if essential is None or mask is None:
                inlier_counts.append(0)
                cheirality_counts.append(0)
                continue
            inlier_counts.append(int(mask.sum()))
            try:
                cheirality, _, _, _ = cv2.recoverPose(
                    essential, keypoints0, keypoints1, camera_matrix, mask=mask
                )
            except cv2.error:
                cheirality = 0
            cheirality_counts.append(int(cheirality))
        evaluations.append(
            {
                "focal_pixels": focal,
                "median_essential_inliers": float(np.median(inlier_counts)),
                "mean_essential_inliers": float(np.mean(inlier_counts)),
                "median_cheirality_inliers": float(np.median(cheirality_counts)),
                "mean_cheirality_inliers": float(np.mean(cheirality_counts)),
            }
        )
    evaluations.sort(
        key=lambda item: (
            -item["median_cheirality_inliers"],
            -item["mean_cheirality_inliers"],
            -item["median_essential_inliers"],
            item["focal_pixels"],
        )
    )
    result = {
        "schema_version": 1,
        "method": "shared SIMPLE_PINHOLE focal grid using essential-matrix RANSAC and recoverPose",
        "principal_point_pixels": [360.0, 640.0],
        "candidate_min_pixels": min(candidates),
        "candidate_max_pixels": max(candidates),
        "candidate_step_pixels": 25,
        "pair_count": len(pair_records),
        "pair_names": [[item[0], item[1]] for item in pair_records],
        "ranking": evaluations,
        "selected_focal_pixels": evaluations[0]["focal_pixels"],
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
