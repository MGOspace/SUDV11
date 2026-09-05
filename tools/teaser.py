#!/usr/bin/env python3
"""
Fabrique une image teaser : un coin du plan, rendu avec la meme geometrie
que le prototype (silhouettes ecrasees au contact, un col noir entre deux
bulles liees). Rendu en 2x puis reduit, pour l'antialiasing.

  python3 tools/teaser.py [sortie.jpg] [graine]
"""
import sys, os, json, math, random
import numpy as np
from PIL import Image

W, H, SS = 1600, 1000, 2
BG = (242, 236, 224)     # cale sur --plan-bg de pics.html
SQUASH = 0.13
ROOT = os.path.expanduser("~/Desktop/SUDV11.pics")


def square(im):
    w, h = im.size
    s = min(w, h)
    return im.crop(((w - s)//2, (h - s)//2, (w + s)//2, (h + s)//2))


def main():
    global W, H
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Desktop/SUDV11_teaser.jpg")
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else random.randrange(10**6)
    if len(sys.argv) > 4: W, H = int(sys.argv[3]), int(sys.argv[4])
    neck = "--sans-lien" not in sys.argv
    rng = random.Random(seed)

    meta = json.load(open("assets/atlas.json"))
    pool = [e for e in meta["images"] if not e["file"].startswith("arena/")]

    w, h = W * SS, H * SS
    # --- placement : depot aleatoire puis relaxation ---
    dens = (W * H) / (1600.0 * 1000.0)
    n = max(8, int(round(26 * dens)))
    R = [rng.uniform(96, 152) * SS for _ in range(n)]
    P = [[rng.uniform(0, w), rng.uniform(0, h)] for _ in range(n)]
    for _ in range(400):
        for i in range(n):
            for j in range(i + 1, n):
                dx, dy = P[j][0]-P[i][0], P[j][1]-P[i][1]
                d = math.hypot(dx, dy) or 1
                ov = R[i] + R[j] - d - 6*SS      # -6 : on laisse les bords se toucher
                if ov > 0:
                    ux, uy = dx/d, dy/d
                    P[i][0] -= ux*ov*0.5; P[i][1] -= uy*ov*0.5
                    P[j][0] += ux*ov*0.5; P[j][1] += uy*ov*0.5
        for i in range(n):
            P[i][0] = min(w + R[i]*0.5, max(-R[i]*0.5, P[i][0]))
            P[i][1] = min(h + R[i]*0.5, max(-R[i]*0.5, P[i][1]))

    # --- contacts, pour l'ecrasement des silhouettes ---
    contacts = [[] for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j: continue
            dx, dy = P[j][0]-P[i][0], P[j][1]-P[i][1]
            d = math.hypot(dx, dy) or 1
            gap = d - R[i] - R[j]
            if gap < 10*SS:
                st = min(1.0, max(0.0, (10*SS - gap) / (26*SS)))
                if st > 0.02: contacts[i].append((dx/d, dy/d, st))
    contacts = [sorted(c, key=lambda t: -t[2])[:2] for c in contacts]

    canvas = Image.new("RGB", (w, h), BG)

    # --- le col noir : la paire la plus enfoncee ---
    # on cherche une paire ecartee d'un tiers de rayon : le col se voit,
    # au lieu d'etre noye dans le chevauchement
    best, bd = None, 1e9
    for i in range(n):
        for j in range(i+1, n):
            gap = math.hypot(P[j][0]-P[i][0], P[j][1]-P[i][1]) - R[i] - R[j]
            score = abs(gap - 0.10*min(R[i], R[j]))
            if score < bd: bd, best = score, (i, j)
    a, b = best
    k = 0.50 * min(R[a], R[b])
    ra, rb = R[a], R[b]
    x0 = int(min(P[a][0]-R[a], P[b][0]-R[b]) - k); x1 = int(max(P[a][0]+R[a], P[b][0]+R[b]) + k)
    y0 = int(min(P[a][1]-R[a], P[b][1]-R[b]) - k); y1 = int(max(P[a][1]+R[a], P[b][1]+R[b]) + k)
    x0, y0 = max(0, x0), max(0, y0); x1, y1 = min(w, x1), min(h, y1)
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d1 = np.hypot(xx-P[a][0], yy-P[a][1]) - ra
    d2 = np.hypot(xx-P[b][0], yy-P[b][1]) - rb
    hh = np.clip(0.5 + 0.5*(d2-d1)/k, 0, 1)
    dd = d2*(1-hh) + d1*hh - k*hh*(1-hh)
    if neck:
        m = Image.fromarray(((dd < 0) * 255).astype(np.uint8), "L")
        canvas.paste(Image.new("RGB", m.size, (0, 0, 0)), (x0, y0), m)

    # --- les bulles ---
    picks = rng.sample(pool, n)
    for i in range(n):
        r = R[i]
        s = int(2*r)
        try:
            im = Image.open(os.path.join(ROOT, picks[i]["file"]))
            im.draft("RGB", (s*2, s*2))
            im = square(im.convert("RGB")).resize((s, s), Image.LANCZOS)
        except Exception:
            continue
        gy, gx = np.mgrid[0:s, 0:s].astype(np.float32)
        cx = cy = s/2.0
        vx, vy = gx-cx+0.5, gy-cy+0.5
        dist = np.hypot(vx, vy)
        rad = np.ones_like(dist)
        safe = np.maximum(dist, 1e-3)
        for (ux, uy, st) in contacts[i]:
            dot = np.maximum(0.0, (vx*ux + vy*uy) / safe)
            rad -= SQUASH * st * dot**3
        mask = np.clip((rad*r - dist) * 1.4 + 0.5, 0, 1)
        canvas.paste(im, (int(P[i][0]-r), int(P[i][1]-r)),
                     Image.fromarray((mask*255).astype(np.uint8), "L"))

    canvas.resize((W, H), Image.LANCZOS).save(out, quality=92, optimize=True)
    print("%s  (graine %d, %d bulles)" % (out, seed, n))


if __name__ == "__main__":
    main()
