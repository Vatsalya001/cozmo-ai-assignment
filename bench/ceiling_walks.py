"""G-CEIL and G-CEIL-SPREAD: our ceiling height against FARO laser truth, on full walks.

Each ARKitScenes Validation walk in the upsampling list publishes two depth streams registered
to the same frames and the same trajectory: `lowres_depth` from the device, and `highres_depth`
rendered from a FARO laser scan. Fuse either with the walk's own poses and the whole pipeline
downstream of depth can be run twice on identical geometry. The difference is our error against
a surveying instrument.

This is the measurement this project most needed and twice failed to get.

## What the two earlier attempts got wrong

`bench/arkitscenes_laser.py` compared storey heights against venue point clouds and returned
NOT MEASURED: the clouds spanned 5 m with no dominant floor layer, because ARKitScenes venues
are mostly multi-storey.

`bench/ceiling_vs_laser.py` then used the **upsampling split**, which publishes laser depth for
7 to 38 isolated frames per scan -- sampled for training a depth model, not a continuous walk --
and concluded there was "never enough coverage to reconstruct a room". That conclusion was
correct about the upsampling split and wrong about the dataset. A video listed in that split
also exists as a full raw Validation walk, and *that* walk publishes laser depth across the
trajectory. One download gives a complete walk and its truth. Nothing about the data changed;
only which slice of it to ask for.

**Credit:** that this slice exists was learned from the dataset-fetch script of an independent
submission to the same brief, which measures G-CEIL this way. The venues here are selected by a stated rule rather than copied
(see scripts/fetch_arkitscenes_walks.py), and the pipeline being measured is ours -- but the
approach is theirs, and this project had already published the wrong conclusion that no such
measurement was available.

## Both sides go through OUR fitting

The laser cloud is run through `planes.floor_and_ceiling` exactly as the device cloud is, not
compared against Apple's annotations. So a weakness in our plane fitting would partly cancel on
both sides, which is why **the device-minus-laser difference is the number reported** rather
than either height on its own. What this measures is our geometry on device depth against our
geometry on laser-grade depth.

## The bias correction is held out, because it has to be

Correcting device depth using an offset measured on the same walk would be fitting on the test
set: the correction would absorb the very error being reported. So the offset applied to a walk
is the median device-minus-laser disparity measured on **the other venue's** walks. No walk is
corrected with its own truth, and the uncorrected numbers are reported alongside so the
correction's effect is visible rather than assumed.

    python bench/ceiling_walks.py
    python bench/ceiling_walks.py --no-bias-correction
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanplan.geometry import planes                               # noqa: E402

cv2.setNumThreads(0)

ROOT = Path(__file__).resolve().parents[1]
WALKS = ROOT / "data" / "arkitscenes_walks"
OUT = ROOT / "bench" / "results" / "ceiling_walks.json"

DEPTH_SHAPE = (192, 256)   # the device grid; the laser stream is resampled onto it
DEPTH_MIN_M, DEPTH_MAX_M = 0.40, 5.00
PIXEL_STRIDE = 2
VOXEL_M = 0.02
GATE_CEIL_M = 0.015         # G-CEIL: ceiling height within 1.5 cm of truth
GATE_SPREAD_M = 0.010       # G-CEIL-SPREAD: within 1 cm across walks of one venue
BIAS_MIN_M, BIAS_MAX_M = 0.30, 2.00     # near range, where registration is most reliable


# ARKitScenes world is z-up; everything else in this project is y-up like Stray Scanner.
# (x, y, z) -> (x, z, -y).
Z_UP_TO_Y_UP = np.array([[1.0, 0.0, 0.0],
                         [0.0, 0.0, 1.0],
                         [0.0, -1.0, 0.0]])


def read_traj(path: Path):
    """Poses as world_from_cam in a y-up world.

    Three conventions had to be right here and all three were wrong in this project's two
    earlier attempts, which is why both returned NOT MEASURED:

    1. `lowres_wide.traj` rotation is **cam_from_world**, not world_from_cam, so it must be
       inverted. Used as-is it scatters the cloud and no surface dominates any height band.
    2. The translation is in the camera frame for the same reason: the world position is
       `-R_cw^-1 t`, not `t`.
    3. The ARKitScenes world is **z-up**, while this project and Stray Scanner are y-up.

    Credit: all three are documented in the ARKitScenes ingest of an independent submission to
    the same brief. Guessing at them cost two benchmarks and a wrong published
    conclusion, which is a fair price for not reading the format carefully the first time.
    """
    rows = [l.split() for l in path.read_text().splitlines() if len(l.split()) >= 7]
    if not rows:
        return np.array([]), np.array([])
    rows.sort(key=lambda r: float(r[0]))
    stamps = np.array([float(r[0]) for r in rows])
    rvec = np.array([[float(r[1]), float(r[2]), float(r[3])] for r in rows])
    tvec = np.array([[float(r[4]), float(r[5]), float(r[6])] for r in rows])

    cam_from_world = Rotation.from_rotvec(rvec)
    to_y_up = Rotation.from_matrix(Z_UP_TO_Y_UP)
    world_from_cam = to_y_up * cam_from_world.inv()
    positions = to_y_up.apply(-cam_from_world.inv().apply(tvec))

    poses = np.tile(np.eye(4), (len(rows), 1, 1))
    poses[:, :3, :3] = world_from_cam.as_matrix()
    poses[:, :3, 3] = positions
    return stamps, poses


def intrinsics_for(walk: Path, key: str, shape):
    cand = sorted((walk / "lowres_wide_intrinsics").glob(f"*_{key}.pincam"))
    if not cand:
        return None
    iw, ih, fx, fy, cx, cy = (float(v) for v in cand[0].read_text().split())
    h, w = shape
    sx, sy = w / iw, h / ih
    return fx * sx, fy * sy, (cx + 0.5) * sx - 0.5, (cy + 0.5) * sy - 0.5


def frames_of(walk: Path, which: str) -> dict[str, Path]:
    d = walk / which
    return {f.stem.split("_", 1)[1]: f for f in d.glob("*.png")} if d.is_dir() else {}


def fuse(walk: Path, which: str, offset_m: float = 0.0, keys: list[str] | None = None):
    """World cloud from one depth source, using the walk's own poses."""
    traj = walk / "lowres_wide.traj"
    if not traj.is_file():
        return None, None
    stamps, poses = read_traj(traj)
    files = frames_of(walk, which)
    use = keys if keys is not None else sorted(files)

    pts, cam_y = [], []
    for key in use:
        f = files.get(key)
        if f is None:
            continue
        t = float(key)
        j = int(np.argmin(np.abs(stamps - t)))
        if abs(stamps[j] - t) > 0.05:
            continue
        raw = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
        if raw is None:
            continue
        depth = raw.astype(np.float32) / 1000.0
        # The laser stream is 1440x1920 where the device is 192x256 -- 56x the pixels. Fused at
        # full resolution it produced 322 million points and never finished. Resampling it to
        # the device grid keeps the laser *values* (nearest, no interpolation between surfaces)
        # and makes the two clouds comparable in density, which the height histogram needs:
        # 56x more laser points would dominate any statistic computed over both.
        if depth.shape != DEPTH_SHAPE:
            depth = cv2.resize(depth, (DEPTH_SHAPE[1], DEPTH_SHAPE[0]),
                               interpolation=cv2.INTER_NEAREST)
        if offset_m:
            depth = np.where(depth > 0, depth + np.float32(offset_m), depth)

        k = intrinsics_for(walk, key, depth.shape)
        if k is None:
            continue
        fx, fy, cx, cy = k
        h, w = depth.shape
        sub = depth[::PIXEL_STRIDE, ::PIXEL_STRIDE]
        v, u = np.mgrid[0:h:PIXEL_STRIDE, 0:w:PIXEL_STRIDE]
        keep = (sub > DEPTH_MIN_M) & (sub < DEPTH_MAX_M)
        if not keep.any():
            continue
        z = sub[keep]
        cam = np.stack([(u[keep] - cx) / fx * z, (v[keep] - cy) / fy * z, z], axis=1)
        pts.append(cam @ poses[j][:3, :3].T + poses[j][:3, 3])
        cam_y.append(poses[j][1, 3])

    if not pts:
        return None, None
    P = np.vstack(pts)
    # Voxel-reduce so the height histogram is comparable between the two sources, which have
    # different native resolutions and would otherwise weight surfaces differently.
    keys_v = np.floor(P / VOXEL_M).astype(np.int64)
    _, first = np.unique(keys_v, axis=0, return_index=True)
    return P[np.sort(first)], np.array(cam_y)


def disparity(walk: Path) -> float | None:
    """Median device-minus-laser depth on this walk, over frames both streams publish."""
    dev, las = frames_of(walk, "lowres_depth"), frames_of(walk, "highres_depth")
    shared = sorted(set(dev) & set(las))
    if not shared:
        return None
    diffs = []
    for key in shared:
        a = cv2.imread(str(dev[key]), cv2.IMREAD_UNCHANGED)
        b = cv2.imread(str(las[key]), cv2.IMREAD_UNCHANGED)
        if a is None or b is None:
            continue
        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST)
        a = a.astype(np.float32) / 1000.0
        b = b.astype(np.float32) / 1000.0
        m = ((a > BIAS_MIN_M) & (a < BIAS_MAX_M) & (b > BIAS_MIN_M) & (b < BIAS_MAX_M)
             & (np.abs(a - b) < 0.30))        # over 30 cm apart is registration, not bias
        if m.any():
            diffs.append((a[m] - b[m]))
    if not diffs:
        return None
    return float(np.median(np.concatenate(diffs)))


def storey(points, cam_y):
    floor, ceiling = planes.floor_and_ceiling(points, cam_y)
    if floor is None or ceiling is None:
        return None
    h, sigma = planes.ceiling_height(floor, ceiling)
    return {"ceiling_height_m": h, "sigma_m": sigma,
            "floor_m": floor.height_m, "ceiling_m": ceiling.height_m}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-bias-correction", action="store_true",
                    help="use depth as recorded; the ablation half of the measurement")
    args = ap.parse_args()

    manifest_path = WALKS / "manifest.json"
    if not manifest_path.is_file():
        print(f"{manifest_path.relative_to(ROOT)} missing. Run "
              f"scripts/fetch_arkitscenes_walks.py first.", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())

    # Per-walk disparity first: needed both as a reported number and to build the held-out
    # correction. Measured on frames where BOTH streams exist, which is what makes it per-pixel.
    disp = {}
    for m in manifest:
        walk = WALKS / "Validation" / m["video_id"]
        d = disparity(walk)
        if d is not None:
            disp[m["video_id"]] = d
        print(f"  {m['video_id']}: disparity "
              f"{'n/a' if d is None else f'{d*1000:+.1f} mm'}")

    visits = sorted({m["visit_id"] for m in manifest})
    rows = []
    for m in manifest:
        vid, visit = m["video_id"], m["visit_id"]
        walk = WALKS / "Validation" / vid

        # Leave-one-venue-out: the offset for this walk comes from the OTHER venues only.
        other = [d for k, d in disp.items()
                 if any(n["video_id"] == k and n["visit_id"] != visit for n in manifest)]
        offset = 0.0 if args.no_bias_correction else (-float(np.median(other)) if other else 0.0)

        shared = sorted(set(frames_of(walk, "lowres_depth")) & set(frames_of(walk, "highres_depth")))
        dev_pts, dev_cam = fuse(walk, "lowres_depth", offset_m=offset, keys=shared)
        las_pts, las_cam = fuse(walk, "highres_depth", keys=shared)
        if dev_pts is None or las_pts is None:
            rows.append({"video_id": vid, "visit_id": visit,
                         "rejected": "no usable cloud from one of the two depth streams"})
            print(f"  {vid}: no usable cloud")
            continue

        sd, sl = storey(dev_pts, dev_cam), storey(las_pts, las_cam)
        if sd is None or sl is None:
            rows.append({"video_id": vid, "visit_id": visit,
                         "rejected": f"no floor+ceiling pair (device {'ok' if sd else 'no'}, "
                                     f"laser {'ok' if sl else 'no'})",
                         "frames_used": len(shared)})
            print(f"  {vid}: no floor+ceiling pair "
                  f"(device {'ok' if sd else 'no'}, laser {'ok' if sl else 'no'})")
            continue

        err = sd["ceiling_height_m"] - sl["ceiling_height_m"]
        rows.append({
            "video_id": vid, "visit_id": visit,
            "frames_used": len(shared),
            "applied_offset_mm": round(offset * 1000, 1),
            "device": {k: round(v, 4) for k, v in sd.items()},
            "laser": {k: round(v, 4) for k, v in sl.items()},
            "ceiling_error_mm": round(err * 1000, 1),
            "within_gate": bool(abs(err) <= GATE_CEIL_M),
        })
        print(f"  {vid}: device {sd['ceiling_height_m']:.3f} m  laser "
              f"{sl['ceiling_height_m']:.3f} m  error {err*1000:+6.1f} mm  "
              f"{'within 15 mm' if abs(err) <= GATE_CEIL_M else 'OUTSIDE'}")

    scored = [r for r in rows if "ceiling_error_mm" in r]
    result = {
        "gate": "G-CEIL: ceiling height within 1.5 cm of truth",
        "method": "device depth and FARO-derived laser depth fused with the SAME poses on the "
                  "same frames, both run through OUR floor/ceiling fit; the difference is "
                  "reported rather than either height alone",
        "bias_correction": "none" if args.no_bias_correction else "leave-one-venue-out",
        "credit": "the full raw Validation walk carries laser depth across the trajectory, not "
                  "just the 7-38 upsampling frames this project first looked at. Learned from "
                  "an independent submission to the same brief, which measures G-CEIL this "
                  "way",
        "caveat": "the laser side goes through our fitting, not Apple's annotations, so a "
                  "fitting weakness would partly cancel on both sides. This measures our "
                  "geometry on device depth against our geometry on laser-grade depth",
        "per_walk_disparity_mm": {k: round(v * 1000, 1) for k, v in disp.items()},
        "rows": rows,
        "walks_scored": len(scored),
        "walks_rejected": len(rows) - len(scored),
    }

    if scored:
        errs = np.array([r["ceiling_error_mm"] for r in scored])
        within = sum(r["within_gate"] for r in scored)
        result.update({
            "within_gate": within, "total": len(scored),
            "mean_error_mm": round(float(errs.mean()), 1),
            "median_error_mm": round(float(np.median(errs)), 1),
            "max_abs_error_mm": round(float(np.abs(errs).max()), 1),
            "gate_met": within == len(scored),
        })
        # G-CEIL-SPREAD: agreement across walks of ONE venue.
        spread = {}
        for v in visits:
            hs = [r["device"]["ceiling_height_m"] for r in scored if r["visit_id"] == v]
            if len(hs) >= 2:
                spread[str(v)] = round((max(hs) - min(hs)) * 1000, 1)
        result["spread_within_venue_mm"] = spread
        ok = [v for v, s in spread.items() if s <= GATE_SPREAD_M * 1000]
        result["spread_gate"] = {
            "target_mm": GATE_SPREAD_M * 1000,
            "venues_within": f"{len(ok)}/{len(spread)}" if spread else "0/0",
            "gate_met": bool(spread) and len(ok) == len(spread),
        }
        print(f"\n  G-CEIL: {within}/{len(scored)} walks within 15 mm   "
              f"mean {errs.mean():+.1f} mm   worst {np.abs(errs).max():.1f} mm   "
              f"{'MET' if within == len(scored) else 'NOT MET'}")
        print(f"  G-CEIL-SPREAD: {spread}   "
              f"{'MET' if result['spread_gate']['gate_met'] else 'NOT MET'} "
              f"(target {GATE_SPREAD_M*1000:.0f} mm)")
    else:
        print("\n  no walk produced a floor and ceiling from both streams: NOT MEASURED")

    # The ablation writes beside the measurement, not over it: both halves are the evidence.
    dest = OUT if not args.no_bias_correction else OUT.with_name("ceiling_walks_uncorrected.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nwrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
