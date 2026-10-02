"""Score a photo-tier capture folder so the 8 that ship are chosen, not taken in filename order.

`scanplan/ingest/photos.py` keeps `images[:MAX_PER_ROOM]` -- the first eight by sorted filename,
which on an iPhone is simply the first eight taken. That is fine when exactly eight were shot and
silently wrong when more were: the extras are dropped without a word, and the ones dropped are
whichever happened to be last.

This reports the mechanical signals a human cannot eyeball reliably, so the visual choice is made
on the remainder:

  ORIENTATION   portrait is a hard reject. The tier resizes every still to a fixed 256x192 grid
                without preserving aspect while carrying one focal length for both axes, so a
                portrait photo is stretched 1.78x and every length from it is wrong. cv2.imread
                applies the EXIF orientation tag, so this is detectable here exactly as the tier
                will see it.
  SHARPNESS     variance of the Laplacian. Motion blur destroys the depth model's edges, and the
                floor-plane fit needs them.
  EXPOSURE      share of pixels crushed to black or blown to white. Both are regions where the
                depth model has nothing to work from.
  FLOOR-ISH     share of image area in the lower third that is not crushed black. The tier
                recovers gravity per photo by fitting a floor plane and DROPS any photo where it
                fails (`if levelled is None: continue`), so a frame with no visible floor is a
                silent loss. This is a weak proxy -- it cannot tell floor from rug from shadow --
                so it flags candidates for a human to confirm rather than deciding anything.

Nothing here is a verdict. It is a shortlist plus the two hard facts (portrait, and unreadably
dark or blurred) that do not need judgement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEPTH_W, DEPTH_H = 256, 192          # must match scanplan/ingest/photos.py
MAX_PER_ROOM = 8
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def score(path: Path) -> dict | None:
    bgr = cv2.imread(str(path))
    if bgr is None:
        return {"name": path.name, "unreadable": True}
    h, w = bgr.shape[:2]
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(grey, (512, 384), interpolation=cv2.INTER_AREA)

    aspect = w / max(h, 1)
    sx, sy = DEPTH_W / w, DEPTH_H / h
    anisotropy = max(sx, sy) / min(sx, sy)

    lower = small[int(small.shape[0] * 0.66):, :]
    return {
        "name": path.name,
        "w": w, "h": h,
        "portrait": w < h,
        "anisotropy": anisotropy,
        "sharpness": float(cv2.Laplacian(small, cv2.CV_64F).var()),
        "dark_frac": float((small < 16).mean()),
        "blown_frac": float((small > 245).mean()),
        "lower_lit_frac": float((lower >= 16).mean()),
        "unreadable": False,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: triage_photos.py <folder> [<folder> ...]")
    for folder in argv[1:]:
        d = Path(folder)
        if not d.is_dir():
            print(f"{folder}: not a directory")
            continue
        imgs = sorted(p for p in d.iterdir() if p.suffix.lower() in EXTS)
        print(f"\n=== {d}  ({len(imgs)} photos, the tier will keep {MAX_PER_ROOM}) ===")
        if not imgs:
            print("  (empty)")
            continue
        rows = [score(p) for p in imgs]
        ok = [r for r in rows if not r["unreadable"]]
        sharp = sorted(r["sharpness"] for r in ok)
        median_sharp = sharp[len(sharp) // 2] if sharp else 0.0

        print(f"  {'file':28s} {'size':>11s} {'orient':>9s} {'sharp':>8s} "
              f"{'dark':>6s} {'blown':>6s} {'lowlit':>7s}  flags")
        for r in rows:
            if r["unreadable"]:
                print(f"  {r['name']:28s}  UNREADABLE")
                continue
            flags = []
            if r["portrait"]:
                flags.append(f"PORTRAIT-REJECT({r['anisotropy']:.2f}x stretch)")
            elif r["anisotropy"] > 1.01:
                flags.append(f"not-4:3({r['anisotropy']:.2f}x)")
            if median_sharp and r["sharpness"] < 0.45 * median_sharp:
                flags.append("soft")
            if r["dark_frac"] > 0.35:
                flags.append("dark")
            if r["blown_frac"] > 0.12:
                flags.append("blown")
            if r["lower_lit_frac"] < 0.55:
                flags.append("little-floor?")
            print(f"  {r['name']:28s} {r['w']:5d}x{r['h']:<5d} "
                  f"{'portrait' if r['portrait'] else 'LANDSCAPE':>9s} "
                  f"{r['sharpness']:8.1f} {r['dark_frac']:6.2f} {r['blown_frac']:6.2f} "
                  f"{r['lower_lit_frac']:7.2f}  {' '.join(flags)}")

        usable = [r for r in ok if not r["portrait"]]
        print(f"  -> {len(usable)} usable (landscape), {len(ok) - len(usable)} portrait rejects")
        if len(usable) < MAX_PER_ROOM:
            print(f"  !! fewer than {MAX_PER_ROOM} usable photos; coverage may be short")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
