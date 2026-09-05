#!/usr/bin/env python3
"""
Fabrique l'atlas de vignettes pour le plan d'images.

  python3 tools/build_atlas.py ~/Desktop/SUDV11.pics assets/

Sort :
  assets/atlas_0.jpg   planche 4096x4096, une seule
  assets/atlas.json    { cell, grid, size, images: [{ i, atlas, x, y, w, h }] }

Les vignettes sont recadrees au carre (centre) : les bulles sont rondes.
L'image pleine resolution reste a part, elle n'est chargee qu'a l'ouverture.

Le plan ne charge qu'une planche : la cellule est donc la plus grande qui
fasse tenir toutes les images sur 4096, sans jamais depasser CELL_MAX.

Les images absentes de l'atlas precedent sont marquees "nuit" : ce sont les
dernieres arrivees, et le plan les depose ensemble dans l'angle en bas a
gauche. Le marquage se conserve d'une reconstruction a l'autre.

ATTENTION — l'etat partage du plan (clics et liens, cote Worker) est indexe
par la POSITION de l'image dans la liste ci-dessous, elle-meme triee par nom
de fichier. Ajouter ou retirer une seule photo decale les positions et
reattribue silencieusement les clics et les liens de tous les visiteurs a
d'autres images. Mesure faite : apres l'ajout de 75 photos, aucun des 480
index precedents ne designait encore la meme photo.

Donc : si l'atlas change apres la mise en ligne, il faut remettre l'etat
partage a zero (route /reset du Worker) — ou passer les cles du Worker sur un
identifiant stable plutot que sur la position.
"""
import sys, os, json, glob
from PIL import Image, ImageFilter

CELL_MAX = 176      # cote d'une vignette : au-dela on ne gagne plus rien a
                    # l'ecran, la bulle n'est jamais si grande
ATLAS = 4096        # cote d'une planche
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")


def square(im):
    w, h = im.size
    s = min(w, h)
    return im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))


def main():
    root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/Desktop/SUDV11.pics")
    dest = sys.argv[2] if len(sys.argv) > 2 else "assets"
    os.makedirs(dest, exist_ok=True)

    files = []
    for dirpath, _, names in os.walk(root):
        for n in sorted(names):
            if not n.startswith(".") and n.lower().endswith(EXTS):
                files.append(os.path.join(dirpath, n))
    files.sort()

    # Ce que l'atlas precedent connaissait deja : tout le reste vient d'arriver.
    # Sans atlas precedent (premiere construction), personne n'est nouveau.
    ancien = os.path.join(dest, "atlas.json")
    connus, nuit = set(), set()
    if os.path.exists(ancien):
        try:
            vieux = json.load(open(ancien))
            for e in vieux.get("images", []):
                connus.add(e["file"])
                if e.get("nuit"):
                    nuit.add(e["file"])
        except Exception:
            connus = set()

    # une seule planche : la cellule s'adapte au nombre d'images
    grid = 1
    while grid * grid < max(1, len(files)):
        grid += 1
    CELL = min(CELL_MAX, ATLAS // grid)
    GRID = ATLAS // CELL
    print("%d images -> cellule %d px, grille %dx%d" % (len(files), CELL, GRID, GRID))

    images, sheets = [], []
    sheet = None
    for i, p in enumerate(files):
        a, cell = divmod(i, GRID * GRID)
        if a == len(sheets):
            sheet = Image.new("RGB", (ATLAS, ATLAS), (12, 12, 12))
            sheets.append(sheet)
        cy, cx = divmod(cell, GRID)
        try:
            im = Image.open(p)
            im.draft("RGB", (CELL * 2, CELL * 2))   # decodage JPEG accelere
            im = square(im.convert("RGB")).resize((CELL, CELL), Image.LANCZOS)
            # la reduction ramollit : on rend un peu de nervosite avant l'encodage
            im = im.filter(ImageFilter.UnsharpMask(radius=1.1, percent=62, threshold=2))
        except Exception as e:
            print("  ignore %s (%s)" % (os.path.basename(p), e))
            continue
        sheets[a].paste(im, (cx * CELL, cy * CELL))
        w, h = Image.open(p).size
        rel = os.path.relpath(p, root)
        e = {"i": len(images), "atlas": a, "x": cx, "y": cy,
             "file": rel, "w": w, "h": h}
        if rel in nuit or (connus and rel not in connus):
            e["nuit"] = 1          # arrivee tardive : elle ira dans le coin
        images.append(e)
        print("\r  %d/%d" % (i + 1, len(files)), end="", file=sys.stderr)

    for a, s in enumerate(sheets):
        s.save(os.path.join(dest, "atlas_%d.jpg" % a), quality=87, optimize=True)

    meta = {"cell": CELL, "atlas": ATLAS, "grid": GRID,
            "sheets": len(sheets), "images": images}
    with open(os.path.join(dest, "atlas.json"), "w") as f:
        json.dump(meta, f)

    n_nuit = sum(1 for e in images if e.get("nuit"))
    print("\n\n%d images -> %d planche(s), dont %d dans le coin"
          % (len(images), len(sheets), n_nuit))
    for a in range(len(sheets)):
        p = os.path.join(dest, "atlas_%d.jpg" % a)
        print("  atlas_%d.jpg  %.1f Mo" % (a, os.path.getsize(p) / 1e6))
    print("  atlas.json   %.0f Ko" % (os.path.getsize(os.path.join(dest, "atlas.json")) / 1e3))


if __name__ == "__main__":
    main()
