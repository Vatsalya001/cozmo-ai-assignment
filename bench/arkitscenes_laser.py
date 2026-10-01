"""Measure the device depth bias against FARO laser ground truth.

SUPERSEDED: this returned NOT MEASURED and blamed multi-storey venues. G-CEIL is measured in
bench/ceiling_walks.py -- 5 of 5 walks within 15 mm -- once the trajectory is read correctly
(cam_from_world, inverted, z-up). Kept as the record of the first of two wrong conclusions.

Storey height is the right quantity to calibrate on, for two reasons.

It is **frame-independent**: the laser clouds sit in a site datum with Z near 393 m and the
iPad walks sit in an ARKit frame starting at the origin, and registering one to the other is
a whole problem of its own. The distance between floor and ceiling does not care.

And it **doubles the signal**. If the sensor reads long by d, the floor -- seen by looking
down -- lands d too low, and the ceiling -- seen by looking up -- lands d too high. So

    measured storey - laser storey = 2d

which means a 12 mm bias shows up as a 24 mm discrepancy, comfortably above the noise of a
plane fit over hundreds of thousands of points.

    python bench/arkitscenes_laser.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanplan.geometry import fusion, planes                      # noqa: E402
from scanplan.ingest import arkitscenes                           # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "arkitscenes"
OUT = ROOT / "bench" / "results" / "arkitscenes_laser.json"


def level_peak(values: np.ndarray, bin_m: float = 0.01) -> tuple[float, int]:
    """Strongest 1 cm layer, refined to the centroid of its neighbourhood."""
    lo, hi = values.min(), values.max()
    counts, edges = np.histogram(values, bins=max(int((hi - lo) / bin_m), 1))
    centre = (edges[counts.argmax()] + edges[counts.argmax() + 1]) / 2
    near = values[np.abs(values - centre) < 0.03]
    return float(near.mean()), int(len(near))


def laser_storey(ply: Path) -> dict:
    """Floor and ceiling of a FARO scan. Its vertical axis is Z."""
    pts = arkitscenes.laser_levels(ply, max_points=3_000_000)
    z = pts[:, 2]
    mid = np.median(z)
    floor, nf = level_peak(z[z < mid])
    ceiling, nc = level_peak(z[z > mid])
    return {"file": ply.name, "floor_m": floor, "ceiling_m": ceiling,
            "storey_m": ceiling - floor, "floor_points": nf, "ceiling_points": nc}


def device_storey(scan_dir: Path, stride: int = 4) -> dict | None:
    ir = arkitscenes.load(scan_dir, stride=stride)
    fusion.fuse(ir)
    # ARKit's world frame is gravity-aligned with Y up, so the vertical axis is fixed and is
    # NOT inferred. Picking the axis with the most concentrated height histogram was tried and
    # is actively dangerous: it chose Z for one scan and Y for another in the same venue, and
    # the two then disagreed by 790 mm while their mean looked like a respectable -20 mm bias.
    # A wrong answer that averages to a plausible one is the worst failure mode available.
    axis = 1
    heights = ir.points[:, axis]
    cam = np.median(ir.trajectory[:, axis])
    below, above = heights[heights < cam - 0.10], heights[heights > cam + 0.10]
    if len(below) < 1000 or len(above) < 1000:
        return None
    floor, nf = level_peak(below)
    ceiling, nc = level_peak(above)
    storey = ceiling - floor

    # Two admissibility checks. Without them this benchmark will happily average a pair of
    # wrong answers into a plausible-looking one, which is worse than reporting nothing.
    rejected = None
    camera_rise = float(ir.trajectory[:, axis].max() - ir.trajectory[:, axis].min())
    if camera_rise > 1.20:
        rejected = (f"the camera changed height by {camera_rise:.2f} m, so this is not a "
                    f"single-level walk and there is no one floor to measure from")
    elif not 2.0 <= storey <= 4.0:
        rejected = (f"storey height {storey:.2f} m is outside any plausible range, so the "
                    f"peak found above the camera is not the ceiling")

    return {"scan": scan_dir.name, "vertical_axis": "xyz"[axis], "frames": len(ir.frames),
            "floor_m": floor, "ceiling_m": ceiling, "storey_m": storey,
            "camera_rise_m": camera_rise, "floor_points": nf, "ceiling_points": nc,
            "rejected": rejected}


def main() -> int:
    lasers = sorted((DATA / "laser_scanner_point_clouds").rglob("*.ply"))
    scans = sorted(p for p in (DATA / "raw").glob("*/*")
             if p.is_dir() and not p.name.startswith(".") and (p / "lowres_depth").is_dir())
    if not lasers or not scans:
        print("no ARKitScenes data found; run scripts/fetch_external.py first", file=sys.stderr)
        return 2

    print(f"laser scans: {len(lasers)}   device scans: {len(scans)}\n")

    laser_rows = [laser_storey(p) for p in lasers]
    for r in laser_rows:
        print(f"  laser {r['file']:<16} floor {r['floor_m']:8.3f}  ceiling {r['ceiling_m']:8.3f}"
              f"  storey {r['storey_m']:.4f} m")

    # The laser scans cover one venue from several stations; their storey heights should agree,
    # and the spread across them is the reference's own uncertainty.
    storeys = np.array([r["storey_m"] for r in laser_rows])
    reference = float(np.median(storeys))
    spread = float(storeys.max() - storeys.min())
    print(f"\n  reference storey height {reference:.4f} m  (spread across stations {spread*1000:.1f} mm)")

    device_rows, rejected_rows = [], []
    for s in scans:
        row = device_storey(s)
        if row is None:
            print(f"  device {s.name}: no ceiling seen, skipped")
            continue
        if row["rejected"]:
            print(f"  device {s.name:<12} REJECTED: {row['rejected']}")
            rejected_rows.append(row)
            continue
        row["laser_storey_m"] = reference
        row["difference_m"] = row["storey_m"] - reference
        row["implied_bias_m"] = row["difference_m"] / 2
        device_rows.append(row)
        print(f"  device {s.name:<12} storey {row['storey_m']:.4f} m  "
              f"vs laser {reference:.4f}  ->  {row['difference_m']*1000:+.1f} mm  "
              f"implied depth bias {row['implied_bias_m']*1000:+.1f} mm")

    result = {"laser": laser_rows, "reference_storey_m": reference,
              "reference_spread_m": spread, "device": device_rows,
              "rejected": rejected_rows}
    if not device_rows:
        result["conclusion"] = (
            "NOT MEASURED. Every downloaded scan failed admissibility, so no depth bias is "
            "claimed and the pipeline keeps its unmeasured 12 mm allowance. More single-level "
            "scans with a clearly observed ceiling are needed.")
        print("\n  NO ADMISSIBLE SCAN: depth bias remains UNMEASURED.")
        print("  The 12 mm allowance in planes.py stays flagged as an assumption, not a result.")
    if device_rows:
        biases = np.array([r["implied_bias_m"] for r in device_rows])
        result["mean_bias_m"] = float(biases.mean())
        result["bias_spread_m"] = float(biases.max() - biases.min()) if len(biases) > 1 else 0.0
        print(f"\n  MEAN IMPLIED DEPTH BIAS: {biases.mean()*1000:+.1f} mm "
              f"over {len(biases)} scans")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
