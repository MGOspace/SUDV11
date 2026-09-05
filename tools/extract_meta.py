#!/usr/bin/env python3
"""
Extrait les metadonnees des photos d'un dossier local -> JSON.

  python3 tools/extract_meta.py ~/Desktop/SUDV11.pics [sortie.json]

Sortie : une entree par photo, avec
  file    nom du fichier
  md5     hash du fichier (cle de jointure possible avec Are.na)
  date    date, ISO 8601
  source  d'ou vient la date, par ordre de fiabilite decroissante :
            exif      -> DateTimeOriginal, vraie heure de prise de vue
            spotlight -> idem, lu par macOS (HEIC/RAW)
            nom       -> horodatage dans le nom de fichier (export WhatsApp :
                         heure d'ENVOI dans la conversation, pas de prise de vue)
            fichier   -> date de modification du fichier, ne veut rien dire
  gps     [lat, lon] si present
  w, h    dimensions
  make    appareil

HEIC : lu via Spotlight (mdls), qui expose l'EXIF sur macOS.
JPEG/PNG/TIFF/WEBP : lus via Pillow.
"""
import sys, os, json, hashlib, subprocess, re
from datetime import datetime

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif", ".dng", ".raf", ".cr2", ".nef", ".arw"}
PILLOW_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def deg(v, ref):
    try:
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
    except Exception:
        return None
    return -d if ref in ("S", "W") else d


def from_pillow(path):
    try:
        from PIL import Image, ExifTags
    except ImportError:
        return {}
    try:
        im = Image.open(path)
        out = {"w": im.width, "h": im.height}
        ex = im.getexif()
        if not ex:
            return out
        tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
        sub = ex.get_ifd(0x8769) or {}
        tags.update({ExifTags.TAGS.get(k, k): v for k, v in sub.items()})
        raw = tags.get("DateTimeOriginal") or tags.get("DateTimeDigitized") or tags.get("DateTime")
        if raw:
            try:
                out["date"] = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S").isoformat()
                out["source"] = "exif"
            except ValueError:
                pass
        if tags.get("Make"):
            out["make"] = str(tags["Make"]).strip("\x00 ")
        g = ex.get_ifd(0x8825) or {}
        if g:
            gt = {ExifTags.GPSTAGS.get(k, k): v for k, v in g.items()}
            lat = deg(gt.get("GPSLatitude", []), gt.get("GPSLatitudeRef", "N"))
            lon = deg(gt.get("GPSLongitude", []), gt.get("GPSLongitudeRef", "E"))
            if lat is not None and lon is not None:
                out["gps"] = [round(lat, 6), round(lon, 6)]
        return out
    except Exception:
        return {}


# WhatsApp nomme ses exports PHOTO-2026-08-30-09-46-39.jpg / VIDEO-...
# = l'heure d'ENVOI dans la conversation, pas l'heure de prise de vue.
NAME_DATE = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})[-_ ](\d{2})[-_.](\d{2})[-_.](\d{2})")


def from_name(path):
    m = NAME_DATE.search(os.path.basename(path))
    if not m:
        return {}
    y, mo, d, h, mi, s = m.groups()
    try:
        datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    except ValueError:
        return {}
    return {"date": "%s-%s-%sT%s:%s:%s" % (y, mo, d, h, mi, s), "source": "nom"}


def from_spotlight(path):
    """macOS : mdls lit l'EXIF des HEIC/RAW sans dependance externe."""
    keys = ["kMDItemContentCreationDate", "kMDItemLatitude", "kMDItemLongitude",
            "kMDItemPixelWidth", "kMDItemPixelHeight", "kMDItemAcquisitionModel"]
    try:
        r = subprocess.run(["mdls"] + sum([["-name", k] for k in keys], []) + [path],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return {}
    vals = {}
    for line in r.stdout.splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*(.+?)\s*$", line)
        if m and m.group(2) != "(null)":
            vals[m.group(1)] = m.group(2).strip('"')
    out = {}
    d = vals.get("kMDItemContentCreationDate")
    if d:
        try:
            out["date"] = datetime.strptime(d[:19], "%Y-%m-%d %H:%M:%S").isoformat()
            out["source"] = "spotlight"
        except ValueError:
            pass
    if vals.get("kMDItemLatitude") and vals.get("kMDItemLongitude"):
        out["gps"] = [round(float(vals["kMDItemLatitude"]), 6), round(float(vals["kMDItemLongitude"]), 6)]
    if vals.get("kMDItemPixelWidth"):
        out["w"] = int(float(vals["kMDItemPixelWidth"]))
        out["h"] = int(float(vals["kMDItemPixelHeight"]))
    if vals.get("kMDItemAcquisitionModel"):
        out["make"] = vals["kMDItemAcquisitionModel"]
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    root = os.path.expanduser(sys.argv[1])
    dest = sys.argv[2] if len(sys.argv) > 2 else "photos_meta.json"

    files = []
    for dirpath, _, names in os.walk(root):
        for n in sorted(names):
            if n.startswith("."):
                continue
            if os.path.splitext(n)[1].lower() in EXTS:
                files.append(os.path.join(dirpath, n))

    rows = []
    for i, p in enumerate(files, 1):
        ext = os.path.splitext(p)[1].lower()
        info = from_pillow(p) if ext in PILLOW_EXTS else {}
        if "date" not in info:
            info = {**from_spotlight(p), **info}
        if "date" not in info:
            info = {**from_name(p), **info}
        if "date" not in info:
            info["date"] = datetime.fromtimestamp(os.path.getmtime(p)).isoformat()
            info["source"] = "fichier"
        rows.append({
            "file": os.path.relpath(p, root),
            "md5": md5(p),
            "bytes": os.path.getsize(p),
            "date": info.get("date"),
            "source": info.get("source"),
            "gps": info.get("gps"),
            "w": info.get("w"), "h": info.get("h"),
            "make": info.get("make"),
        })
        print("\r%d/%d" % (i, len(files)), end="", file=sys.stderr)

    rows.sort(key=lambda r: r["date"] or "")
    with open(dest, "w") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)

    n = len(rows)
    par = {}
    for r in rows:
        par[r["source"]] = par.get(r["source"], 0) + 1
    print("\n\n%d photos -> %s" % (n, dest))
    for k, v in sorted(par.items()):
        print("  date issue de %-10s : %d" % (k, v))
    print("  avec GPS             : %d" % sum(1 for r in rows if r["gps"]))
    if rows and rows[0]["date"]:
        print("  periode              : %s  ->  %s" % (rows[0]["date"][:10], rows[-1]["date"][:10]))


if __name__ == "__main__":
    main()
