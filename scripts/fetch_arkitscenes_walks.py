"""Fetch full ARKitScenes Validation walks that carry laser-derived depth.

    python scripts/fetch_arkitscenes_walks.py                 # the default 2 venues, 6 walks
    python scripts/fetch_arkitscenes_walks.py --visits 381644  # one venue
    python scripts/fetch_arkitscenes_walks.py --list           # candidates, download nothing

## Why this exists, and the mistake it corrects

`bench/ceiling_vs_laser.py` reported G-CEIL as NOT MEASURED and gave three reasons, the third
being that the upsampling split "publishes 7 to 38 isolated frames per scan, not a continuous
walk, so there is never enough coverage to reconstruct a room". That is accurate about the
upsampling split and it was the wrong place to look.

The fix: a video that appears in the upsampling split also exists as a **full raw Validation
walk**, and that walk publishes `highres_depth` -- laser-derived depth registered to its own
frames -- for a large fraction of the trajectory rather than a handful of training samples. So
one download gives a complete walk *and* its laser truth. Nothing about the dataset changed;
only which slice of it to ask for.

**Credit where it is due:** that this slice exists was learned from reading
`scripts/fetch_external.py` in https://github.com/ashupal22/cozmo-scan, an independent
submission to the same brief, which measures G-CEIL this way. The venue *selection* below is
not taken from there -- it falls out of a stated criterion -- but the approach is theirs and
this project had concluded, wrongly, that the measurement was not available.

## Selection criterion, stated so it can be checked

From `raw/metadata.csv`: walks in the **Validation** fold with `is_in_upsampling == True`,
grouped by `visit_id`, keeping visits with **at least three** walks. Three matters twice: a
leave-one-venue-out bias correction needs more than one venue, and G-CEIL-SPREAD is about
agreement *across walks of one venue*, which needs several. 97 visits qualify; the first two in
`visit_id` order are taken, which is an arbitrary but stated rule rather than a search for
venues that flatter the result.

`lowres_wide` (RGB, 135 MB per walk) is deliberately not fetched. Ceiling height needs depth,
intrinsics and poses; downloading images to leave them unread would triple the transfer.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "arkitscenes_walks"
BASE = "https://docs-assets.developer.apple.com/ml-research/datasets/arkitscenes/v1"

# lowres_depth = device depth; highres_depth = laser-derived truth, same frames.
ZIP_ASSETS = ["lowres_depth", "confidence", "highres_depth", "lowres_wide_intrinsics"]
FILE_ASSETS = ["lowres_wide.traj"]
MIN_WALKS_PER_VISIT = 3
DEFAULT_VISITS = 2


def download(url: str, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("content-length", 0))
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {dst.name}: {done/1e6:.0f}/{total/1e6:.0f} MB", end="", flush=True)
    print()
    tmp.rename(dst)
    return dst


def candidates() -> dict[int, list[str]]:
    meta = download(f"{BASE}/raw/metadata.csv", OUT / "metadata.csv")
    rows = list(csv.DictReader(open(meta, newline="")))
    by = collections.defaultdict(list)
    for r in rows:
        if (r["fold"] == "Validation" and r.get("is_in_upsampling") == "True"
                and r["visit_id"] not in ("", "NA")):
            by[int(float(r["visit_id"]))].append(r["video_id"])
    return {k: v for k, v in sorted(by.items()) if len(v) >= MIN_WALKS_PER_VISIT}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--visits", nargs="+", type=int, help="visit ids (default: first 2)")
    ap.add_argument("--list", action="store_true", help="show candidates and exit")
    args = ap.parse_args()

    pool = candidates()
    if args.list:
        print(f"{len(pool)} visits with >= {MIN_WALKS_PER_VISIT} Validation upsampling walks")
        for k, v in list(pool.items())[:20]:
            print(f"  visit {k}: {v}")
        return 0

    chosen = args.visits or list(pool)[:DEFAULT_VISITS]
    missing = [v for v in chosen if v not in pool]
    if missing:
        print(f"visits not in the candidate pool: {missing}", file=sys.stderr)
        return 1

    manifest = []
    for visit in chosen:
        for video in pool[visit]:
            walk = OUT / "Validation" / video
            print(f"visit {visit}, walk {video}")
            for asset in ZIP_ASSETS:
                if (walk / asset).is_dir():
                    continue
                z = download(f"{BASE}/raw/Validation/{video}/{asset}.zip", walk / f"{asset}.zip")
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(walk)
                z.unlink()
            for asset in FILE_ASSETS:
                download(f"{BASE}/raw/Validation/{video}/{asset}", walk / asset)
            n_dev = len(list((walk / "lowres_depth").glob("*.png"))) if (walk / "lowres_depth").is_dir() else 0
            n_gt = len(list((walk / "highres_depth").glob("*.png"))) if (walk / "highres_depth").is_dir() else 0
            print(f"    {n_dev} device depth frames, {n_gt} laser depth frames")
            manifest.append({"visit_id": visit, "video_id": video,
                             "device_frames": n_dev, "laser_frames": n_gt})

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\ndone: {len(manifest)} walks in {OUT.relative_to(ROOT)}")
    print("laser frames per walk: " + ", ".join(str(m["laser_frames"]) for m in manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
