#!/usr/bin/env python3
import json
from pathlib import Path

import pycolmap
from PIL import Image, ImageDraw


BASE = Path("/root/scene_recon/outputs/room1/m3/base")
REVIEW = Path("/root/scene_recon/outputs/room1/m3/review/camera_coverage")


def contiguous_spans(indices):
    spans = []
    if not indices:
        return spans
    start = previous = indices[0]
    for index in indices[1:]:
        if index != previous + 1:
            spans.append([start, previous])
            start = index
        previous = index
    spans.append([start, previous])
    return spans


def main() -> None:
    REVIEW.mkdir(parents=True, exist_ok=True)
    output = REVIEW / "registration_coverage_all_frames.jpg"
    timeline_path = REVIEW / "registration_coverage_timeline.json"
    if output.exists() or timeline_path.exists():
        raise SystemExit("refusing existing registration coverage review")

    reconstruction = pycolmap.Reconstruction(BASE / "sparse")
    registered = {image.name for image in reconstruction.images.values()}
    images = sorted((BASE / "images").glob("frame_*.jpg"))
    tile_width, tile_height = 180, 340
    columns = 12
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "white")
    draw = ImageDraw.Draw(sheet)
    registered_indices = []
    unregistered_indices = []
    for position, path in enumerate(images):
        index = int(path.stem.split("_")[-1])
        is_registered = path.name in registered
        (registered_indices if is_registered else unregistered_indices).append(index)
        with Image.open(path) as source:
            thumbnail = source.convert("RGB").resize((174, 309), Image.Resampling.LANCZOS)
        x = (position % columns) * tile_width
        y = (position // columns) * tile_height
        border = (20, 150, 60) if is_registered else (210, 40, 40)
        sheet.paste(thumbnail, (x + 3, y + 3))
        draw.rectangle((x + 1, y + 1, x + 178, y + 337), outline=border, width=4)
        draw.text((x + 7, y + 315), f"{index:03d}  {(index - 1) / 2:.1f}s", fill=(0, 0, 0))
        draw.text((x + 105, y + 315), "REG" if is_registered else "MISS", fill=border)
    sheet.save(output, quality=92)
    timeline = {
        "schema_version": 1,
        "frame_count": len(images),
        "registered_count": len(registered_indices),
        "unregistered_count": len(unregistered_indices),
        "registered_spans_one_based_inclusive": contiguous_spans(registered_indices),
        "unregistered_spans_one_based_inclusive": contiguous_spans(unregistered_indices),
        "nominal_timestamp_formula": "(one_based_frame_index - 1) / 2 seconds",
        "sheet": str(output),
    }
    timeline_path.write_text(json.dumps(timeline, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(timeline, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
