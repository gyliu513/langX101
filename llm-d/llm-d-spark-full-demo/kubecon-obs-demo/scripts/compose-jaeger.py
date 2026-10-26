#!/usr/bin/env python3
"""Compose the Jaeger slide image from real UI captures.

Inputs (from capture-jaeger.py): tree.png (span tree, 2x), table0..2.png (the
Tags tables of match_block_keys, scorer.prefix-cache-scorer and llm_request,
other tags hidden), rows.json (row positions, CSS px). The tables are pasted
next to their rows in the empty part of the timeline and the rows are boxed
A / B / C, so the values stay legible at slide size.

  compose-jaeger.py <capture dir> <out.png>
"""
import json
import sys

from PIL import Image, ImageDraw, ImageFont

RED = (220, 38, 38)
d, out = sys.argv[1], sys.argv[2]
rows = json.load(open(f"{d}/rows.json"))
tree = Image.open(f"{d}/tree.png").convert("RGB")
S = 2                                   # device scale factor of the capture
top = int(rows["header"]["y"] - 6) * S
bottom = int(rows["llm_request"]["y"] + rows["llm_request"]["height"] + 6) * S
img = tree.crop((0, top, tree.width, bottom))
draw = ImageDraw.Draw(img)
font = None
for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
    try:
        font = ImageFont.truetype(path, 34)
        break
    except OSError:
        pass
font = font or ImageFont.load_default()

ImageOps = __import__("PIL.ImageOps", fromlist=["ImageOps"])
name_col = int(rows["name_col"]) * S     # right edge of the span-name column
inset_x = name_col + 90
slots = [230, 500, 770]                 # y of each inset in the cropped image
for i, (key, label) in enumerate([("match_block_keys", "A"), ("scorer.prefix-cache", "B"),
                                   ("llm_request", "C")]):
    r = rows[key]
    y0 = int(r["y"]) * S - top
    y1 = y0 + int(r["height"]) * S
    draw.rounded_rectangle((4, y0 - 2, name_col - 4, y1 + 2), radius=8, outline=RED, width=5)
    t = Image.open(f"{d}/table{i}.png").convert("RGB")
    bbox = ImageOps.invert(t.convert("L")).point(lambda v: 255 if v > 40 else 0).getbbox()
    t = t.crop((0, 0, min(t.width, bbox[2] + 30), t.height))   # trim to the values
    scale = min(1.4, (img.width - inset_x - 12) / t.width)
    t = t.resize((int(t.width * scale), int(t.height * scale)))
    ty = slots[i]
    img.paste(t, (inset_x, ty))
    draw.rounded_rectangle((inset_x - 4, ty - 4, inset_x + t.width + 4, ty + t.height + 4),
                           radius=8, outline=RED, width=5)
    draw.line((name_col - 4, (y0 + y1) // 2, inset_x - 4, ty + t.height // 2), fill=RED, width=4)
    bx, by = inset_x - 4, ty - 4
    draw.rounded_rectangle((bx - 50, by, bx - 6, by + 44), radius=8, fill=RED)
    draw.text((bx - 28, by + 22), label, fill="white", font=font, anchor="mm")
img.save(out)
print("wrote", out, img.size)
