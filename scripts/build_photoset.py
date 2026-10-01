"""Build the photo-tier benchmark input deterministically from a supplied capture.

## Why this script exists

`bench/photo_tier.py` used to default to `/tmp/photoset`, a folder assembled by hand during
development. The temp directory was cleaned up, so the photo tier's only committed benchmark
rested on an input that no longer existed anywhere -- unreproducible in the strongest sense:
not "gives different numbers" but "cannot be run at all". The clean-clone check could not catch
it, because that benchmark needs the model extra and is skipped by default.

So the input is now generated, from committed data, at fixed frame indices. Same capture in,
same stills out, on any machine.

## What this input is, and what it is not

These are **stills cut from a walked capture's RGB stream**, grouped into folders by the
segment of the walk they came from. They are not photographs someone took of their rooms.

That distinction bounds what the photo tier benchmark may claim:

- **Legitimate:** does the tier ingest per-room folders, infer depth, level each view against
  its own floor, produce a room box per folder, and leave the folders unstitched? That is
  G-PHOTO-STITCH, and it is a property of the method, not of the input.
- **Not legitimate:** any accuracy number. Nobody has tape-measured this property, and a
  segment of a walk is not a room. `bench/photo_tier.py` records the grouping and the
  footprint and explicitly declines to score accuracy, which is the correct call.

The segments are also only *approximately* per-room. A walk passes through rooms over time, so
an early segment and a late segment usually see different places -- but no annotation says
where one room ends. Calling them `segment_a` and `segment_b` rather than `kitchen` and
`bedroom` keeps that honest: the folder names claim adjacency in time, which is true, not
identity of room, which is not established.

    python scripts/build_photoset.py                 # writes data/derived/photoset/
    python scripts/build_photoset.py --out /tmp/x    # somewhere else
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "data" / "supplied" / "single_room" / "c00a170fe1"
DEFAULT_OUT = ROOT / "data" / "derived" / "photoset"

# Two disjoint windows of the walk, as a fraction of its length, and the stills to take from
# each. Six is inside the brief's 2-8 per room. The windows avoid the first and last 8% of the
# walk, where the phone is being picked up and put down.
SEGMENTS = {"segment_a": (0.08, 0.40), "segment_b": (0.60, 0.92)}
PER_SEGMENT = 6


def build(capture: Path, out: Path, per_segment: int = PER_SEGMENT) -> dict[str, int]:
    video = capture / "rgb.mp4"
    if not video.is_file():
        raise SystemExit(f"{video}: not found. The supplied captures must be at data/supplied "
                         f"(a symlink is fine); they are fetched, not committed.")

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"{video}: cannot be opened")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        raise SystemExit(f"{video}: reports no frames")

    written = {}
    for name, (lo, hi) in SEGMENTS.items():
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        for existing in folder.glob("*.jpg"):
            existing.unlink()                      # rebuild cleanly, never half-stale

        first, last = int(lo * (total - 1)), int(hi * (total - 1))
        step = max((last - first) // max(per_segment - 1, 1), 1)
        kept = 0
        for k in range(per_segment):
            idx = min(first + k * step, total - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, bgr = cap.read()
            if not ok:
                continue
            # Quality 95: the tier downsamples to 512x384 for the depth model anyway, so the
            # only thing compression could cost here is depth-model input quality.
            cv2.imwrite(str(folder / f"{name}_{idx:06d}.jpg"), bgr,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            kept += 1
        written[name] = kept
        print(f"  {name}: {kept} stills from frames {first}-{last} of {total}")

    cap.release()
    if not any(written.values()):
        raise SystemExit(f"{video}: no frame could be decoded")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capture", default=str(CAPTURE), help="Stray Scanner folder to cut from")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="where to write the room folders")
    ap.add_argument("--per-segment", type=int, default=PER_SEGMENT)
    args = ap.parse_args()

    out = Path(args.out)
    print(f"cutting {args.per_segment} stills per segment from {Path(args.capture).name}")
    build(Path(args.capture), out, args.per_segment)
    print(f"\nwrote {out}")
    print("these are stills cut from a walked capture, not photographs of rooms; see the "
          "module docstring for what the photo-tier benchmark may and may not claim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
