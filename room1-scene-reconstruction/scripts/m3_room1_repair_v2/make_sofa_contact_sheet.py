#!/usr/bin/env python3
"""Build a denser contact sheet around the registered sofa views."""

from pathlib import Path
import re
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT = Path('/root/scene_recon')
BASE = ROOT / 'outputs/room1/m3_repair_v2/base'
OUTPUT = ROOT / 'outputs/room1/m3_repair_v2/review/sofa_candidates_130_175.jpg'

sys.path.insert(0, str(ROOT / 'repos/PlanarGS'))
from scene.colmap_loader import read_extrinsics_binary

extrinsics = read_extrinsics_binary(str(BASE / 'sparse/images.bin'))
names = sorted(image.name for image in extrinsics.values())
selected = [name for name in names if 130 <= int(re.search(r'\d+', name).group()) <= 175]
thumb_w, thumb_h, label_h, columns = 180, 320, 24, 6
rows = (len(selected) + columns - 1) // columns
canvas = Image.new('RGB', (columns * thumb_w, rows * (thumb_h + label_h)), 'white')
draw = ImageDraw.Draw(canvas)
font = ImageFont.load_default()
for index, name in enumerate(selected):
    image = Image.open(BASE / 'images' / name).convert('RGB')
    image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
    x = (index % columns) * thumb_w
    y = (index // columns) * (thumb_h + label_h)
    canvas.paste(image, (x, y))
    draw.text((x + 4, y + thumb_h + 5), name, fill='black', font=font)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
canvas.save(OUTPUT, quality=94)
print(OUTPUT, len(selected))
