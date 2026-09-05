#!/usr/bin/env python3
"""
Petit atlas pour l'accueil : le plan vit derriere la page, mais on ne voit
que ce qui traverse les lettres. Quelques dizaines d'images suffisent.

  python3 tools/build_mini.py [graine]

Sort assets/mini.jpg (1024x1024, 8x8 cellules de 128 px) et assets/mini.json
"""
import sys, os, json, random
from PIL import Image, ImageFilter

CELL, SHEET = 128, 1024
GRID = SHEET // CELL          # 8 -> 64 images
ROOT = os.path.expanduser("~/Desktop/SUDV11.pics")


def square(im):
    w, h = im.size
    s = min(w, h)
    return im.crop(((w - s)//2, (h - s)//2, (w + s)//2, (h + s)//2))


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    meta = json.load(open("assets/atlas.json"))
    pool = [e["file"] for e in meta["images"] if not e["file"].startswith("arena/")]
    picks = random.Random(seed).sample(pool, GRID * GRID)

    sheet = Image.new("RGB", (SHEET, SHEET), (12, 12, 12))
    kept = []
    for i, f in enumerate(picks):
        try:
            im = Image.open(os.path.join(ROOT, f))
            im.draft("RGB", (CELL * 2, CELL * 2))
            im = square(im.convert("RGB")).resize((CELL, CELL), Image.LANCZOS)
            im = im.filter(ImageFilter.UnsharpMask(radius=1.0, percent=55, threshold=2))
        except Exception:
            continue
        cy, cx = divmod(len(kept), GRID)
        sheet.paste(im, (cx * CELL, cy * CELL))
        kept.append({"x": cx, "y": cy})

    sheet.save("assets/mini.jpg", quality=88, optimize=True)
    json.dump({"cell": CELL, "sheet": SHEET, "grid": GRID, "images": kept},
              open("assets/mini.json", "w"))
    print("%d images -> assets/mini.jpg (%.0f Ko)"
          % (len(kept), os.path.getsize("assets/mini.jpg") / 1e3))


if __name__ == "__main__":
    main()
