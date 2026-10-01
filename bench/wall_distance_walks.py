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
from wall_normals import fuse_with_normals                           # noqa: E402
from scanplan.geometry import planes, regularize, walls              # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "results" / "wall_distance_walks.json"

WALL_BAND = (0.35, 0.25)    # keep points from floor+0.35 m up to ceiling-0.25 m
BIN_M = 0.01
MIN_SUPPORT_FRACTION = 0.004
PEAK_SEPARATION_M = 1.0     # two opposing walls of a room are at least this far apart

# --- orientation-aware selection -------------------------------------------------------
# Density alone cannot tell a wall from a wardrobe side: along one axis both deposit a dense
# 1 cm column. These four tests add what density lacks. See bench/wall_normals.py for the
# provenance of the normals themselves, which is not mine.
VERTICAL_MAX_NY = 0.20      # |n_y| above this is floor, ceiling or a table top, not wall
FACING_COS = float(np.cos(np.radians(12)))   # how far off-axis a surface may face
MIN_COVER_M = 0.50          # a wall runs at least this far along its own direction...
MIN_SPAN_M = 0.80           # ...and this tall. A counter front or a sofa back is lower
COVER_CELL_M = 0.05

# Tied to the estimator's own window rather than left free. A suppression radius WIDER than the
# window the estimator refines over would merge two surfaces it is capable of distinguishing;
# narrower, and one surface answers twice. The previous value was a free 10 bins, which is why
# competitors 0.19 m apart were invisible to it.
PLANE_HALF_M = 0.02
SUPPRESS_BINS = int(round(2 * PLANE_HALF_M / BIN_M))


def wall_points(P: np.ndarray, N: np.ndarray, cam_y: np.ndarray, floor, ceiling):
    """Points that are plausibly wall material: in the height band AND vertically oriented."""
    top = (ceiling.height_m - WALL_BAND[1]) if ceiling else (floor.height_m + 2.2)
    band = (P[:, 1] > floor.height_m + WALL_BAND[0]) & (P[:, 1] < top)
    vertical = np.abs(N[:, 1]) < VERTICAL_MAX_NY
    keep = band & vertical
    return P[keep], N[keep]


def find_planes(P: np.ndarray, N: np.ndarray, axis: int) -> list[dict]:
    """Wall planes perpendicular to `axis`, each with the facing direction it presents.

    Per facing sign separately, because a room's two opposing walls face OPPOSITE ways and
    pooling them would let one wall's front and another's back land in the same histogram bin.
    """
    along = 2 if axis == 0 else 0
    out = []
    for sign in (+1.0, -1.0):
        horiz = N[:, [0, 2]]
        mag = np.linalg.norm(horiz, axis=1)
        col = 0 if axis == 0 else 1
        facing = np.divide(horiz[:, col], mag, out=np.zeros(len(mag)), where=mag > 1e-9)
        sel = (facing * sign) > FACING_COS
        if sel.sum() < 500:
            continue
        pos, side = P[sel, axis], P[sel, along]
        heights = P[sel, 1]

        lo, hi = pos.min(), pos.max()
        if hi - lo < BIN_M:
            continue
        counts, edges = np.histogram(pos, bins=max(int((hi - lo) / BIN_M), 1))
        counts = np.convolve(counts, np.ones(3) / 3.0, mode="same")   # 3 cm smoothing
        centres = (edges[:-1] + edges[1:]) / 2
        need = MIN_SUPPORT_FRACTION * len(pos)

        taken = np.zeros(len(counts), bool)
        for _ in range(8):
            masked = np.where(taken, 0.0, counts)
            k = int(masked.argmax())
            if masked[k] < need:
                break
            taken[max(k - SUPPRESS_BINS, 0):k + SUPPRESS_BINS + 1] = True
            near = np.abs(pos - centres[k]) < PLANE_HALF_M
            if near.sum() < 100:
                continue
            # Extent: a wall is long and tall. Furniture fails one or both.
            cover = len(np.unique(np.floor(side[near] / COVER_CELL_M))) * COVER_CELL_M
            span = float(np.percentile(heights[near], 95) - np.percentile(heights[near], 5))
            if cover < MIN_COVER_M or span < MIN_SPAN_M:
                continue
            out.append({"at": float(pos[near].mean()), "facing": sign,
                        "support": int(near.sum()), "cover_m": round(cover, 3),
                        "span_m": round(span, 3)})
    return out


def opposing_pair(found: list[dict]) -> tuple[dict, dict] | None:
    """The two walls that face EACH OTHER across the room, ranked by the weaker one's extent.

    Facing is what makes this a room measurement rather than a pair of parallel surfaces: the
    wall at the low end must face up-axis and the one at the high end must face down-axis, which
    is only true of surfaces with the room between them.
    """
    best, best_score = None, -1.0
    for a in found:
        for b in found:
            if a["at"] >= b["at"] - PEAK_SEPARATION_M:
                continue
            if not (a["facing"] > 0 and b["facing"] < 0):
                continue
            score = min(a["cover_m"], b["cover_m"])
            if score > best_score:
                best, best_score = (a, b), score
    return best


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


def wall_distances(points: np.ndarray, cam_y: np.ndarray, yaw: float | None = None,
                   normals: np.ndarray | None = None) -> dict | None:
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
    N = regularize.rotate_about_y(normals, yaw) if normals is not None else None

    if N is None:                                   # no normals: the old density-only path
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

    bp, bn = wall_points(P, N, cam_y, floor, ceiling)
    if len(bp) < 2000:
        return None
    out = {"yaw_deg": round(float(np.degrees(yaw)), 2), "wall_points": int(len(bp))}
    for axis, name in ((0, "x"), (2, "z")):
        found = find_planes(bp, bn, axis)
        pair = opposing_pair(found)
        if pair is None:
            # Not a failure to measure accurately -- a failure to FIND a room measurement on
            # this axis at all. Recorded so the shrunken denominator is visible, because a
            # silently dropped axis reads as a measurement that happened to pass.
            out[f"{name}_rejected"] = (
                f"no two wall-sized surfaces face each other across the room on this axis "
                f"({len(found)} wall plane(s) found)")
            continue
        a, b = pair
        out[name] = {"distance_m": round(b["at"] - a["at"], 4),
                     "at": [round(a["at"], 4), round(b["at"], 4)],
                     "support": [a["support"], b["support"]],
                     "cover_m": [a["cover_m"], b["cover_m"]],
                     "span_m": [a["span_m"], b["span_m"]],
                     "planes_found": len(found)}
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
        dev_pts, dev_cam, dev_n = fuse_with_normals(walk, "lowres_depth", offset_m=offset,
                                                    keys=shared)
        las_pts, las_cam, las_n = fuse_with_normals(walk, "highres_depth", keys=shared)
        if dev_pts is None or las_pts is None:
            rows.append({"video_id": vid, "visit_id": visit, "rejected": "no usable cloud"})
            continue

        # One frame for both clouds, taken from the DEVICE cloud -- the one under test.
        shared_yaw = estimate_yaw(dev_pts, dev_cam)
        laser_yaw = estimate_yaw(las_pts, las_cam)      # recorded only, to keep the gap visible
        # Each cloud selects its OWN wall pair. Letting the device choose and the laser merely
        # measure those same surfaces would reach a better number by relaxing what the gate
        # penalises -- it would stop charging us for naming a different valid pair than the
        # laser names. That variant was built, measured at 11/11, and declined; see
        # docs/declined_changes.md section 2.
        wd = wall_distances(dev_pts, dev_cam, yaw=shared_yaw, normals=dev_n)
        wl = wall_distances(las_pts, las_cam, yaw=shared_yaw, normals=las_n)
        if wd is None or wl is None:
            rows.append({"video_id": vid, "visit_id": visit,
                         "rejected": f"no opposing wall pair (device {'ok' if wd else 'no'}, "
                                     f"laser {'ok' if wl else 'no'})"})
            print(f"  {vid}: no opposing wall pair")
            continue

        for name in ("x", "z"):
            if name not in wd or name not in wl:
                why = wd.get(f"{name}_rejected") or wl.get(f"{name}_rejected")
                if why:
                    rows.append({"video_id": vid, "visit_id": visit, "axis": name,
                                 "rejected_axis": why,
                                 "which": "device" if f"{name}_rejected" in wd else "laser"})
                    print(f"  {vid} {name}: axis rejected -- {why}")
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

    rejected_axes = [r for r in rows if "rejected_axis" in r]
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
