#!/usr/bin/env python3
"""Build a compact RGB review sheet from registered COLMAP frames."""

from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


ROOT = Path("/root/scene_recon")
BASE = ROOT / "outputs/room1/m3_repair_v2/base"
OUTPUT = ROOT / "outputs/room1/m3_repair_v2/review/calibration_candidates.jpg"


def main() -> None:
    sys.path.insert(0, str(ROOT / "repos/PlanarGS"))
    from scene.colmap_loader import read_extrinsics_binary

    extrinsics = read_extrinsics_binary(str(BASE / "sparse/images.bin"))
    names = sorted(image.name for image in extrinsics.values())
    # Favor early registered views where the gray sofa is largest, then sample the room loop.
    selected = names[:24] + names[24::12][:16]
    thumb_w, thumb_h = 240, 427
    label_h, columns = 28, 5
    rows = (len(selected) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, name in enumerate(selected):
        image = Image.open(BASE / "images" / name).convert("RGB")
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x = (index % columns) * thumb_w
        y = (index // columns) * (thumb_h + label_h)
        canvas.paste(image, (x, y))
        draw.rectangle((x, y + thumb_h, x + thumb_w, y + thumb_h + label_h), fill="white")
        draw.text((x + 5, y + thumb_h + 6), name, fill="black", font=font)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT, quality=92)
    print(OUTPUT)
    print("selected", len(selected), "registered", len(names))


if __name__ == "__main__":
    main()
