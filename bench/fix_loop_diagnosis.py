"""Evidence behind the fix-loop declaration, regenerable.

Run before declaring, so the root cause is measured on the real captures rather than argued
from a synthetic case. That distinction is the whole difference between a fix loop that moves
its gate and one that earns marks only for the honesty of its post-mortem.

## The rule this file now obeys, and used to break

docs/fix_loop.md §9 records a failed second attempt whose cause was stated as a rule: **a
configuration sweep must call the same entry point the product calls.** That attempt predicted
7-vs-7 rooms and 1.4%, shipped 6-vs-7 and 6.2%, and was reverted.

The rule was declared and then not applied here. This harness reimplemented the pipeline's
geometry stage by hand and omitted drift correction, so its sweep measured a pipeline nobody
ships. The clean-clone check caught it: at the shipped door_max_m the harness reported 4 rooms
from each capture while `scanplan run` reported 5 from each. Both "agree", so the conclusion
the fix loop drew survived -- but it survived by luck, and the next question asked of this
harness would have been answered about the wrong pipeline.

So the sweep now calls `pipeline.run`, the product's own entry point, once per configuration.
It is slower, and that is the correct trade: the sweep is the measurement the shipped value of
DOOR_MAX_M rests on.

`detail()` below still reconstructs the intermediate grids, because `run` returns a document
and the coverage and seed-core diagnostics need the raster that produced it. That makes it a
second implementation of the same steps, which is exactly how the bug arose -- so
`check_harness_matches_product` asserts the two agree at the shipped configuration, and the
script exits non-zero if they ever drift apart again. A rule that is only written down is the
rule that was already broken once.

    python bench/fix_loop_diagnosis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanplan import pipeline                                                 # noqa: E402
from scanplan.geometry import fusion, planes, regularize, rooms as R, walls   # noqa: E402
from scanplan.ingest import stray                                             # noqa: E402
from scanplan.slam import drift as drift_mod                                  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAIR = {"1a8384c3f6": ROOT / "data/supplied/single_scan_floor_only/1a8384c3f6",
        "c7d28f72c6": ROOT / "data/supplied/single_scan_with_ceiling/c7d28f72c6"}
SWEEP = (0.70, 0.80, 0.95, 1.10, 1.30, 1.50)


def detail(path):
    """The pipeline's geometry stage up to the split, kept so the rasters can be inspected.

    This mirrors pipeline.run deliberately, including the drift correction it omitted before.
    check_harness_matches_product() is what keeps the mirror honest.
    """
    ir = stray.load(path, stride=3)
    drift_mod.correct(ir, apply=True)                 # the step this harness used to skip
    fusion.fuse(ir, min_confidence=1)
    fl, _ = planes.floor_and_ceiling(ir.points, ir.trajectory[:, 1])
    probe = walls.density(ir.points, fl.height_m)
    yaw = (walls.dominant_orientations(walls.wall_mask(probe)) or [0.0])[0]
    ir.points = regularize.rotate_about_y(ir.points, yaw)
    g = walls.density(ir.points, fl.height_m)
    wm = walls.wall_mask(g)
    cov = walls.floor_coverage(ir.points, fl.height_m, g)
    free = (cov & ~cv2.dilate(wm, np.ones((3, 3), np.uint8)).astype(bool)).astype(np.uint8)
    return free, g, float(cov.sum() * g.cell_m ** 2), float(free.sum() * g.cell_m ** 2)


def check_harness_matches_product(state, product_counts) -> list[str]:
    """At the shipped configuration the harness must see what `scanplan run` sees."""
    problems = []
    for name, (free, g) in state.items():
        mine = len(R.polygons(R.split_rooms(free, g), g))
        theirs = product_counts[name]
        if mine != theirs:
            problems.append(
                f"{name}: this harness finds {mine} rooms at the shipped configuration but "
                f"scanplan run finds {theirs}. The harness has drifted from the product and "
                f"its diagnostics describe a pipeline nobody ships (docs/fix_loop.md §9)")
    return problems


def main() -> int:
    out = {"coverage": {}, "sweep": {}, "seed_cores": {},
           "sweep_method": "scanplan.pipeline.run, the product's own entry point, once per "
                           "door_max_m; see the module docstring for why this is not optional",
           "shipped_door_max_m": R.DOOR_MAX_M}
    state = {}
    for name, path in PAIR.items():
        free, g, cov_a, free_a = detail(path)
        state[name] = (free, g)
        out["coverage"][name] = {"floor_coverage_m2": cov_a, "after_wall_cut_m2": free_a}
        print(f"{name}: coverage {cov_a:.1f} m2, after wall cut {free_a:.1f} m2")

    print(f"\nroom count vs erosion width, via pipeline.run "
          f"({len(SWEEP)} configurations x {len(PAIR)} captures):")
    product_counts = {}
    for dm in SWEEP:
        counts = {}
        for name, path in PAIR.items():
            counts[name] = len(pipeline.run(path, door_max_m=dm)["rooms"])
        if dm == R.DOOR_MAX_M:
            product_counts = dict(counts)
        out["sweep"][f"{dm:.2f}"] = counts
        agree = len(set(counts.values())) == 1
        print(f"  {dm:.2f}: " + "  ".join(f"{n}={c}" for n, c in counts.items())
              + ("   stable" if agree else "   UNSTABLE")
              + ("   <- shipped" if dm == R.DOOR_MAX_M else ""))

    if not product_counts:
        print(f"\nthe shipped DOOR_MAX_M ({R.DOOR_MAX_M}) is not in SWEEP, so the harness "
              f"cannot be checked against the product")
        return 1

    print(f"\nseed core areas at the shipped {R.DOOR_MAX_M}:")
    for name, (free, g) in state.items():
        cell = g.cell_m
        r = max(int((R.DOOR_MAX_M / 2) / cell), 1)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        n, _, stats, _ = cv2.connectedComponentsWithStats(cv2.erode(free, k), connectivity=4)
        areas = sorted((float(stats[i, cv2.CC_STAT_AREA]) * cell ** 2 for i in range(1, n)),
                       reverse=True)
        out["seed_cores"][name] = {"count": n - 1, "areas_m2": [round(a, 4) for a in areas]}
        print(f"  {name}: {n-1} cores, {[f'{a:.2f}' for a in areas[:10]]}")

    problems = check_harness_matches_product(state, product_counts)
    out["harness_matches_product"] = not problems
    out["harness_mismatch"] = problems

    dest = ROOT / "bench" / "results" / "fix_loop_diagnosis.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {dest.relative_to(ROOT)}")

    if problems:
        print("\nHARNESS DOES NOT MATCH THE PRODUCT:")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"\nharness agrees with scanplan run at the shipped {R.DOOR_MAX_M} on both captures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
