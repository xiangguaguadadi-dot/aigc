#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path("/root/scene_recon")
IMAGE_ROOT = ROOT / "outputs/room1/m3/base/images"
OUTPUT_ROOT = ROOT / "outputs/room1/m3/review/instances"
FRAME_NAMES = [
    "frame_000005.jpg",
    "frame_000020.jpg",
    "frame_000030.jpg",
    "frame_000050.jpg",
    "frame_000060.jpg",
    "frame_000078.jpg",
    "frame_000092.jpg",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    sheet_path = OUTPUT_ROOT / "selected_keyframes.jpg"
    manifest_path = OUTPUT_ROOT / "selected_keyframes.json"
    if sheet_path.exists() or manifest_path.exists():
        raise FileExistsError("refusing to overwrite instance keyframe review")

    font = ImageFont.load_default()
    tile_width, tile_height = 240, 448
    columns, rows = 4, 2
    canvas = Image.new("RGB", (columns * tile_width, rows * tile_height), "white")
    draw = ImageDraw.Draw(canvas)
    records = []

    for index, frame_name in enumerate(FRAME_NAMES):
        frame_path = IMAGE_ROOT / frame_name
        with Image.open(frame_path) as source:
            image = source.convert("RGB")
            image.thumbnail((tile_width, tile_height - 24), Image.Resampling.LANCZOS)
        x = (index % columns) * tile_width + (tile_width - image.width) // 2
        y = (index // columns) * tile_height + 22
        canvas.paste(image, (x, y))
        draw.text((index % columns * tile_width + 5, index // columns * tile_height + 5), frame_name, fill="black", font=font)
        records.append(
            {
                "frame": frame_name,
                "nominal_timestamp_seconds": (int(frame_path.stem.rsplit("_", 1)[1]) - 1) / 2,
                "sha256": sha256(frame_path),
            }
        )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    canvas.save(sheet_path, quality=92, subsampling=0)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_id": "room1_shared_base_v1",
        "selection_policy": (
            "Seven registered frames spanning all four registered capture intervals; "
            "frame_000005 is the immutable sofa scale anchor."
        ),
        "frames": records,
        "sheet": str(sheet_path),
        "sheet_sha256": sha256(sheet_path),
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"manifest_sha256={sha256(manifest_path)}")


if __name__ == "__main__":
    main()
