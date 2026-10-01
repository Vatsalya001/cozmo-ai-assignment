"""A-WALL-LIDAR: wall-to-wall distance against FARO laser truth.

Ceiling height is the distance between two horizontal surfaces. A wall-to-wall distance is the
same measurement turned ninety degrees: the separation of two opposing vertical surfaces. Once
`bench/ceiling_walks.py` could fuse device depth and laser depth onto the same poses, this
followed almost for free -- and it measures the quantity a floor plan is actually made of.

A-WALL-LIDAR is our own gate, not the brief's: <= max(2 cm, 1%). The brief loosens walls to
+-3% for video, so the LiDAR tier has to be tighter, and 1-3 cm is the accuracy incumbents
report.

## Method

Per walk, after yaw-aligning the cloud on its own dominant wall direction exactly as the
pipeline does:

1. Keep points well above the floor and below the ceiling -- wall material, not floor clutter
   or ceiling fixtures.
2. Along each of the two horizontal axes, histogram the coordinate and take the two strongest
   1 cm peaks. Two opposing walls of a room are the two densest vertical planes in that
   direction, for the same reason the floor is the densest horizontal one.
3. The separation of those peaks is the wall-to-wall distance.

Run on the device cloud and the laser cloud, the difference is our error against a surveying
instrument. As with ceiling height, **both sides go through our own fitting**, so a weakness in
the peak finder partly cancels and the device-minus-laser difference is the number reported.

The bias correction is leave-one-venue-out, for the reason given in `ceiling_walks.py`: a
correction measured on the walk being tested would absorb the error being reported.

## What this does not measure

Our *layout* -- the wall segments `scanplan run` emits for a room. This measures the sensor and
the fusion, through our plane fitting, on a room-scale distance. The layout's own wall lengths
still have no truth to check against, because nobody has taped the supplied captures. That
limit is the same one A-WALL-LIDAR carried when it read NOT MEASURED, narrowed rather than
removed.

    python bench/wall_distance_walks.py
    python bench/wall_distance_walks.py --no-bias-correction
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ceiling_walks import (WALKS, disparity, fuse, frames_of)        # noqa: E402
from scanplan.geometry import planes, regularize, walls              # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "results" / "wall_distance_walks.json"

WALL_BAND = (0.35, 0.25)    # keep points from floor+0.35 m up to ceiling-0.25 m
BIN_M = 0.01
MIN_SUPPORT_FRACTION = 0.004
PEAK_SEPARATION_M = 1.0     # two opposing walls of a room are at least this far apart


def two_strongest(coord: np.ndarray) -> tuple[float, float, int, int] | None:
    """The two densest 1 cm planes along one axis, at least PEAK_SEPARATION_M apart."""
    if len(coord) < 2000:
        return None
    lo, hi = coord.min(), coord.max()
    if hi - lo < PEAK_SEPARATION_M:
        return None
    counts, edges = np.histogram(coord, bins=max(int((hi - lo) / BIN_M), 1))
    centres = (edges[:-1] + edges[1:]) / 2
    need = MIN_SUPPORT_FRACTION * len(coord)

    first = int(counts.argmax())
    if counts[first] < need:
        return None
    far = np.abs(centres - centres[first]) >= PEAK_SEPARATION_M
    if not far.any():
        return None
    masked = np.where(far, counts, 0)
    second = int(masked.argmax())
    if counts[second] < need:
        return None

    # Refine each to the centroid of its neighbourhood, as planes._peak does.
    def refine(c):
        near = coord[np.abs(coord - c) < 0.03]
        return float(near.mean()) if len(near) else float(c)

    a, b = refine(centres[first]), refine(centres[second])
    return min(a, b), max(a, b), int(counts[first]), int(counts[second])


def estimate_yaw(points: np.ndarray, cam_y: np.ndarray) -> float | None:
    """The dominant wall direction, from the walls themselves."""
    floor, _ = planes.floor_and_ceiling(points, cam_y)
    if floor is None:
        return None
    probe = walls.density(points, floor.height_m)
    orientations = walls.dominant_orientations(walls.wall_mask(probe))
    return orientations[0] if orientations else 0.0


def wall_distances(points: np.ndarray, cam_y: np.ndarray, yaw: float | None = None) -> dict | None:
    """Opposing-wall separations along both horizontal axes, after yaw alignment.

    `yaw` MUST be supplied by the caller when two clouds are being compared. The first version
    estimated it inside, independently per cloud -- so "the distance along x" meant a different
    direction in the device cloud than in the laser cloud, and the difference between them was
    not a distance error at all. `walls.dominant_orientations` quantises to 1 degree bins, and a
    one-bin disagreement was measured between the two clouds of 41069050 (0.50 vs 1.50 degrees).
    At a metre of along-wall offset that is ~17 mm of apparent plane shift, the same order as the
    20 mm gate.

    The shared frame comes from the cloud UNDER TEST, never from the laser: taking the frame from
    the truth would let the reference choose how the measurement is oriented.
    """
    floor, ceiling = planes.floor_and_ceiling(points, cam_y)
    if floor is None:
        return None

    if yaw is None:
        probe = walls.density(points, floor.height_m)
        orientations = walls.dominant_orientations(walls.wall_mask(probe))
        yaw = orientations[0] if orientations else 0.0
    P = regularize.rotate_about_y(points, yaw)

    top = (ceiling.height_m - WALL_BAND[1]) if ceiling else (floor.height_m + 2.2)
    band = P[(P[:, 1] > floor.height_m + WALL_BAND[0]) & (P[:, 1] < top)]
    if len(band) < 2000:
        return None

    out = {"yaw_deg": round(float(np.degrees(yaw)), 2), "wall_points": int(len(band))}
    for axis, name in ((0, "x"), (2, "z")):
        got = two_strongest(band[:, axis])
        if got is None:
            continue
        lo, hi, n1, n2 = got
        out[name] = {"distance_m": round(hi - lo, 4), "at": [round(lo, 4), round(hi, 4)],
                     "support": [n1, n2]}
    return out if ("x" in out or "z" in out) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-bias-correction", action="store_true")
    args = ap.parse_args()

    man = WALKS / "manifest.json"
    if not man.is_file():
        print(f"{man.relative_to(ROOT)} missing. Run scripts/fetch_arkitscenes_walks.py.",
              file=sys.stderr)
        return 1
    manifest = json.loads(man.read_text())

    disp = {}
    for m in manifest:
        d = disparity(WALKS / "Validation" / m["video_id"])
        if d is not None:
            disp[m["video_id"]] = d

    rows = []
    for m in manifest:
        vid, visit = m["video_id"], m["visit_id"]
        walk = WALKS / "Validation" / vid
        other = [d for k, d in disp.items()
                 if any(n["video_id"] == k and n["visit_id"] != visit for n in manifest)]
        offset = 0.0 if args.no_bias_correction else (-float(np.median(other)) if other else 0.0)

        shared = sorted(set(frames_of(walk, "lowres_depth")) & set(frames_of(walk, "highres_depth")))
        dev_pts, dev_cam = fuse(walk, "lowres_depth", offset_m=offset, keys=shared)
        las_pts, las_cam = fuse(walk, "highres_depth", keys=shared)
        if dev_pts is None or las_pts is None:
            rows.append({"video_id": vid, "visit_id": visit, "rejected": "no usable cloud"})
            continue

        # One frame for both clouds, taken from the DEVICE cloud -- the one under test.
        shared_yaw = estimate_yaw(dev_pts, dev_cam)
        laser_yaw = estimate_yaw(las_pts, las_cam)      # recorded only, to keep the gap visible
        wd = wall_distances(dev_pts, dev_cam, yaw=shared_yaw)
        wl = wall_distances(las_pts, las_cam, yaw=shared_yaw)
        if wd is None or wl is None:
            rows.append({"video_id": vid, "visit_id": visit,
                         "rejected": f"no opposing wall pair (device {'ok' if wd else 'no'}, "
                                     f"laser {'ok' if wl else 'no'})"})
            print(f"  {vid}: no opposing wall pair")
            continue

        for name in ("x", "z"):
            if name not in wd or name not in wl:
                continue
            d, l = wd[name]["distance_m"], wl[name]["distance_m"]
            err = d - l
            gate = max(0.02, 0.01 * l)
            rows.append({
                "video_id": vid, "visit_id": visit, "axis": name,
                "applied_offset_mm": round(offset * 1000, 1),
                "device_m": round(d, 4), "laser_m": round(l, 4),
                "error_mm": round(err * 1000, 1),
                "gate_m": round(gate, 4),
                "within_gate": bool(abs(err) <= gate),
                # Where each cloud put the two planes. This is the diagnosis: when the two
                # clouds disagree by a metre it is almost never the sensor, it is the two runs
                # choosing DIFFERENT pairs of walls. Without these coordinates the reader
                # cannot tell a sensor error from a correspondence failure, and the two call
                # for completely different fixes.
                "device_at": wd[name]["at"], "laser_at": wl[name]["at"],
                # Both clouds are now measured in the device's frame. The laser cloud's own
                # independent estimate is recorded so a reader can see how far apart the two
                # frames would have been -- that disagreement used to land in the error.
                "shared_yaw_deg": None if shared_yaw is None else round(float(np.degrees(shared_yaw)), 2),
                "laser_own_yaw_deg": None if laser_yaw is None else round(float(np.degrees(laser_yaw)), 2),
                "same_walls": bool(
                    abs(wd[name]["at"][0] - wl[name]["at"][0]) < 0.10
                    and abs(wd[name]["at"][1] - wl[name]["at"][1]) < 0.10),
            })
            print(f"  {vid} {name}: device {d:.3f} m  laser {l:.3f} m  "
                  f"error {err*1000:+6.1f} mm  gate {gate*1000:.0f} mm  "
                  f"{'within' if abs(err) <= gate else 'OUTSIDE'}")

    scored = [r for r in rows if "error_mm" in r]
    result = {
        "gate": "A-WALL-LIDAR: wall-to-wall distance within max(2 cm, 1%) -- our gate, not the "
                "brief's; the brief loosens walls to +-3% for video so LiDAR must be tighter",
        "method": "two strongest opposing vertical planes along each horizontal axis, both "
                  "clouds rotated into ONE frame estimated from the DEVICE cloud (never the "
                  "laser), on the same frames and poses, both through our own fitting",
        "known_limitation": "plane selection is a raw histogram argmax, so where two parallel "
                            "surfaces 0.19-0.99 m apart have near-equal support the choice is "
                            "decided on a margin as small as 2.2% and the two clouds can pick "
                            "differently. That is the mechanism behind the catastrophic rows, "
                            "and it is reported rather than filtered: dropping those rows would "
                            "convert a failure into a pass by discarding the failures",
        "bias_correction": "none" if args.no_bias_correction else "leave-one-venue-out",
        "does_not_measure": "our layout's wall segments. This measures the sensor and the "
                            "fusion through our plane fitting on a room-scale distance; the "
                            "wall lengths `scanplan run` emits still have no truth to check "
                            "against, because nobody has taped the supplied captures",
        "rows": rows,
        "distances_scored": len(scored),
        "rejected": len([r for r in rows if "rejected" in r]),
    }
    if scored:
        errs = np.array([r["error_mm"] for r in scored])
        within = sum(r["within_gate"] for r in scored)
        result.update({
            "within_gate": within, "total": len(scored),
            "median_abs_error_mm": round(float(np.median(np.abs(errs))), 1),
            "max_abs_error_mm": round(float(np.abs(errs).max()), 1),
            "gate_met": within == len(scored),
        })
        same = [r for r in scored if r["same_walls"]]
        if same:
            se = np.array([r["error_mm"] for r in same])
            sw = sum(r["within_gate"] for r in same)
            result["where_both_clouds_chose_the_same_walls"] = {
                "distances": len(same),
                "within_gate": sw,
                "median_abs_error_mm": round(float(np.median(np.abs(se))), 1),
                "max_abs_error_mm": round(float(np.abs(se).max()), 1),
                "note": "a sub-result, NOT the gate. Reported because it separates two very "
                        "different failures: where both clouds select the same pair of walls "
                        "the remaining difference is the sensor, and where they do not the "
                        "difference is our plane-pair selection. The gate stays the full set, "
                        "because choosing the wrong walls is our error too",
            }
            print(f"\n  where both clouds chose the SAME walls: {sw}/{len(same)} within gate, "
                  f"median |error| {np.median(np.abs(se)):.1f} mm")
            print(f"  the rest are our plane-pair selection disagreeing, not the sensor")
        print(f"\n  A-WALL-LIDAR: {within}/{len(scored)} within gate   "
              f"median |error| {np.median(np.abs(errs)):.1f} mm   "
              f"worst {np.abs(errs).max():.1f} mm   "
              f"{'MET' if within == len(scored) else 'NOT MET'}")
    else:
        print("\n  no opposing wall pair on any walk: NOT MEASURED")

    dest = OUT if not args.no_bias_correction else OUT.with_name("wall_distance_walks_uncorrected.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nwrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
