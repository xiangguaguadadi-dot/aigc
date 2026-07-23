#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


SOURCE = Path("/root/scene_recon/data/room1/source/wechat_room1_20260722.mp4")
EXPECTED_SHA256 = "2e6964a3270f69a4ac04ae7a0055d3f5418df97d5cd97166428a0ddb2422c74e"
MARKER = Path("/root/scene_recon/outputs/room1/m3/base/base_once.json")
BASE_ID = "room1_shared_base_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_record() -> dict:
    return {
        "schema_version": 1,
        "scene_id": "room1",
        "base_id": BASE_ID,
        "maximum_base_reconstructions": 1,
        "source_video": str(SOURCE),
        "source_sha256": EXPECTED_SHA256,
        "m3a_policy": "preserve_all_static_objects",
        "m3b_removal_authority": "/root/scene_recon/outputs/room1/m3/remove_instances.json",
        "coordinate_contract": "right_handed_z_up_blender_world_meters",
        "scale_anchor_m": 0.7,
    }


def verify_source() -> None:
    if not SOURCE.is_file() or SOURCE.stat().st_size <= 0:
        raise SystemExit(f"missing source video: {SOURCE}")
    actual = sha256(SOURCE)
    if actual != EXPECTED_SHA256:
        raise SystemExit(f"source SHA256 mismatch: {actual}")


def initialize() -> None:
    verify_source()
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    record = expected_record()
    record["initialized_at"] = datetime.now().astimezone().isoformat()
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("ascii")
    try:
        descriptor = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as error:
        raise SystemExit(f"base already initialized; refusing second base: {MARKER}") from error
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(f"base_once_initialized={MARKER}")


def verify() -> None:
    verify_source()
    if not MARKER.is_file():
        raise SystemExit(f"base marker is missing: {MARKER}")
    record = json.loads(MARKER.read_text(encoding="ascii"))
    expected = expected_record()
    for key, value in expected.items():
        if record.get(key) != value:
            raise SystemExit(f"base marker mismatch for {key}: {record.get(key)!r}")
    print(f"base_once_verified={MARKER}")
    print(f"base_id={record['base_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("initialize", "verify"))
    args = parser.parse_args()
    if args.action == "initialize":
        initialize()
    else:
        verify()


if __name__ == "__main__":
    main()
