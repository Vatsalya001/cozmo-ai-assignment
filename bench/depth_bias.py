"""Measure the device depth bias directly, against laser ground truth.

ARKitScenes' upsampling split publishes, for the same frames, the depth the iPad's LiDAR
reported and the depth derived from a FARO laser scan of the same room. Both are registered to
the same camera, so the bias is a per-pixel subtraction rather than anything inferred.

This replaces an earlier attempt that compared *storey heights* and failed. Storey height is
frame-independent, which is why it was attractive, but it is a difference of two fitted
surfaces and it needs a venue with exactly one floor and one ceiling. The ARKitScenes venues
are overwhelmingly not that: of 319 scans screened, the median camera moves 4.8 m vertically,
and the two originally downloaded had point clouds spanning 5 m with no dominant floor layer at
all -- the strongest 5 cm band held 1.8% of points where a real floor holds 10-20%.

Comparing depth to depth removes every one of those assumptions. There is no floor to find, no
ceiling to find, and no venue geometry to be wrong about.

    python bench/depth_bias.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

cv2.setNumThreads(0)

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "data" / "arkitscenes_up" / "upsampling"
OUT = ROOT / "bench" / "results" / "depth_bias.json"

MIN_M, MAX_M = 0.40, 5.00   # the range the device is specified for
MIN_CONFIDENCE = 2          # high-confidence returns only; low ones are not a bias, they are noise


def frame_pairs(scan: Path):
    """(device depth, laser depth, confidence) per frame, matched by timestamp."""
    lo = {p.stem: p for p in (scan / "lowres_depth").glob("*.png")}
    hi = {p.stem: p for p in (scan / "highres_depth").glob("*.png")}
    cf = {p.stem: p for p in (scan / "confidence").glob("*.png")}
    for key in sorted(lo.keys() & hi.keys()):
        d = cv2.imread(str(lo[key]), cv2.IMREAD_UNCHANGED)
        g = cv2.imread(str(hi[key]), cv2.IMREAD_UNCHANGED)
        c = cv2.imread(str(cf[key]), cv2.IMREAD_UNCHANGED) if key in cf else None
        if d is None or g is None:
            continue
        yield key, d.astype(np.float32) / 1000.0, g.astype(np.float32) / 1000.0, c


def compare(device: np.ndarray, laser: np.ndarray, conf) -> np.ndarray:
    """Per-pixel (device - laser) in metres, at the device's resolution.

    The laser depth is published at the RGB resolution, so it is sampled down to the device
    grid with nearest-neighbour. Averaging it would blur across depth discontinuities and
    invent intermediate ranges at every object edge, which is exactly where a bias estimate
    would be most polluted.
    """
    h, w = device.shape
    laser_small = cv2.resize(laser, (w, h), interpolation=cv2.INTER_NEAREST)

    valid = ((device > MIN_M) & (device < MAX_M) &
             (laser_small > MIN_M) & (laser_small < MAX_M))
    if conf is not None:
        c = cv2.resize(conf, (w, h), interpolation=cv2.INTER_NEAREST) if conf.shape != device.shape else conf
        valid &= c >= MIN_CONFIDENCE
    # Discard disagreements too large to be a bias: those are registration errors or a surface
    # one sensor saw and the other did not.
    diff = device - laser_small
    valid &= np.abs(diff) < 0.30
    return diff[valid]


def main() -> int:
    scans = sorted(p for p in UP.glob("*/*") if p.is_dir() and (p / "highres_depth").is_dir())
    if not scans:
        print(f"no upsampling scans under {UP}", file=sys.stderr)
        return 2

    rows, pooled = [], []
    for scan in scans:
        diffs = []
        frames = 0
        for key, dev, las, conf in frame_pairs(scan):
            d = compare(dev, las, conf)
            if len(d) < 500:
                continue
            diffs.append(d)
            frames += 1
        if not diffs:
            print(f"  {scan.name}: no comparable pixels")
            continue
        all_d = np.concatenate(diffs)
        pooled.append(all_d)
        row = {
            "scan": scan.name, "frames": frames, "pixels": int(len(all_d)),
            "median_bias_mm": float(np.median(all_d) * 1000),
            "mean_bias_mm": float(all_d.mean() * 1000),
            "p25_mm": float(np.percentile(all_d, 25) * 1000),
            "p75_mm": float(np.percentile(all_d, 75) * 1000),
            "rms_mm": float(np.sqrt((all_d ** 2).mean()) * 1000),
        }
        rows.append(row)
        print(f"  {scan.name}: {frames} frames, {len(all_d):>8,} px   "
              f"median {row['median_bias_mm']:+6.1f} mm   "
              f"IQR [{row['p25_mm']:+.0f}, {row['p75_mm']:+.0f}]   rms {row['rms_mm']:.0f} mm")

    if not rows:
        print("no scan produced comparable pixels", file=sys.stderr)
        return 1

    everything = np.concatenate(pooled)
    per_scan = np.array([r["median_bias_mm"] for r in rows])
    result = {
        "method": "per-pixel device depth minus laser-derived depth, same frames, "
                  "high-confidence returns only, 0.4-5.0 m, disagreements over 300 mm discarded "
                  "as registration error rather than bias",
        "scans": rows,
        "pooled_median_mm": float(np.median(everything) * 1000),
        "pooled_mean_mm": float(everything.mean() * 1000),
        "spread_across_scans_mm": float(per_scan.max() - per_scan.min()) if len(per_scan) > 1 else 0.0,
        "total_pixels": int(len(everything)),
        "sign_convention": "positive means the device reads LONGER than the laser",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    print(f"\n  POOLED over {len(rows)} scans, {len(everything):,} pixels:")
    print(f"    median bias {result['pooled_median_mm']:+.1f} mm   "
          f"(positive = device reads longer than laser)")
    print(f"    spread across scans {result['spread_across_scans_mm']:.1f} mm")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
