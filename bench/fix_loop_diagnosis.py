"""Evidence behind the fix-loop declaration, regenerable.

Run before declaring, so the root cause is measured on the real captures rather than argued
from a synthetic case. That distinction is the whole difference between a fix loop that moves
its gate and one that earns marks only for the honesty of its post-mortem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanplan.geometry import fusion, planes, regularize, rooms as R, walls   # noqa: E402
from scanplan.ingest import stray                                             # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAIR = {"1a8384c3f6": ROOT / "data/supplied/single_scan_floor_only/1a8384c3f6",
        "c7d28f72c6": ROOT / "data/supplied/single_scan_with_ceiling/c7d28f72c6"}
SWEEP = (0.70, 0.80, 0.95, 1.10, 1.30, 1.50)


def prepared(path):
    ir = stray.load(path, stride=3)
    fusion.fuse(ir)
    fl, _ = planes.floor_and_ceiling(ir.points, ir.trajectory[:, 1])
    probe = walls.density(ir.points, fl.height_m)
    yaw = (walls.dominant_orientations(walls.wall_mask(probe)) or [0.0])[0]
    ir.points = regularize.rotate_about_y(ir.points, yaw)
    g = walls.density(ir.points, fl.height_m)
    wm = walls.wall_mask(g)
    cov = walls.floor_coverage(ir.points, fl.height_m, g)
    free = (cov & ~cv2.dilate(wm, np.ones((3, 3), np.uint8)).astype(bool)).astype(np.uint8)
    return free, g, float(cov.sum() * g.cell_m ** 2), float(free.sum() * g.cell_m ** 2)


def main() -> int:
    out = {"coverage": {}, "sweep": {}, "seed_cores": {}}
    state = {}
    for name, path in PAIR.items():
        free, g, cov_a, free_a = prepared(path)
        state[name] = (free, g)
        out["coverage"][name] = {"floor_coverage_m2": cov_a, "after_wall_cut_m2": free_a}
        print(f"{name}: coverage {cov_a:.1f} m2, after wall cut {free_a:.1f} m2")

    print("\nroom count vs erosion width:")
    for dm in SWEEP:
        counts = {n: len(R.polygons(R.split_rooms(f, g, door_max_m=dm), g))
                  for n, (f, g) in state.items()}
        out["sweep"][f"{dm:.2f}"] = counts
        agree = len(set(counts.values())) == 1
        print(f"  {dm:.2f}: " + "  ".join(f"{n}={c}" for n, c in counts.items())
              + ("   stable" if agree else "   UNSTABLE"))

    print("\nseed core areas at the shipped 0.95:")
    for name, (free, g) in state.items():
        cell = g.cell_m
        r = max(int((0.95 / 2) / cell), 1)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        n, _, stats, _ = cv2.connectedComponentsWithStats(cv2.erode(free, k), connectivity=4)
        areas = sorted((float(stats[i, cv2.CC_STAT_AREA]) * cell ** 2 for i in range(1, n)),
                       reverse=True)
        out["seed_cores"][name] = {"count": n - 1, "areas_m2": [round(a, 4) for a in areas]}
        print(f"  {name}: {n-1} cores, {[f'{a:.2f}' for a in areas[:10]]}")

    dest = ROOT / "bench" / "results" / "fix_loop_diagnosis.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
