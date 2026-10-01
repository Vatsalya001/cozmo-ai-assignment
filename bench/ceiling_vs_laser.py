"""G-CEIL and A-WALL-LIDAR: our geometry against FARO laser ground truth.

The same frames carry two depth maps — the device's and one derived from a FARO laser scan —
and the same poses fuse either into a world cloud. So the whole pipeline downstream of depth
can be run twice on identical geometry and compared: floor, ceiling, storey height, and the
distance between opposing walls.

This is the measurement the project most needed. Every other accuracy number here comes from
either synthetic geometry we built ourselves, or from one tier agreeing with another. This one
is against a surveying instrument.

## SUPERSEDED: the conclusion below was wrong. See bench/ceiling_walks.py

This script concluded that G-CEIL could not be measured from ARKitScenes. **It can, and it is:
5 of 5 walks within 15 mm, mean -4.3 mm.** `bench/ceiling_walks.py` does it.

Two things were wrong here, and the first is the one worth remembering:

1. **Three format facts were being read incorrectly.** The `lowres_wide.traj` rotation is
   cam_from_world and must be inverted; its translation is therefore in the camera frame; and
   the ARKitScenes world is z-up where this project is y-up. With the poses wrong the fused
   cloud has no dominant floor layer -- which is exactly the symptom reported below and blamed
   on the venues. The data was fine. The reader was not.
2. **The upsampling split was the wrong slice.** A video listed there also exists as a full raw
   Validation walk which publishes laser depth across the whole trajectory, 133 to 466 frames
   rather than 7 to 38.

This file is kept, unedited below this notice, because a wrong conclusion stated confidently is
worth more as a record than as a deletion: it is the second time this project explained away a
measurement it had simply failed to take, and the reasoning below reads perfectly convincing.

## Outcome as originally reported: NOT MEASURED, and the reason is in the data

This script runs and is kept, but on everything obtainable it reports NOT MEASURED. Three
approaches were tried and all fail for the same underlying reason — **storey height needs a
capture that covers one floor and one ceiling, and ARKitScenes is overwhelmingly not that.**

1. **Full raw scans + venue laser clouds.** The two downloaded had point clouds spanning 5 m
   with no dominant floor layer: the strongest 5 cm band held 1.8% of points where a real floor
   holds 10-20%. Screening 319 trajectories put the median vertical camera movement at 4.8 m.

2. **Screening by low camera rise.** This selects the wrong thing twice over. A
   floor-to-ceiling sweep moves the phone over a metre — our own capture protocol asks for
   exactly that — so the filter does not separate a storey climb from a sweep. And the scans it
   does select are tiny: the lowest-rise candidate came back with a 0.29 m "storey", a close-up
   of an object rather than a room. Six further scans screened this way produced five with no
   floor/ceiling pair at all.

3. **The upsampling split**, which publishes laser-derived depth registered to the same frames.
   This is the right instrument for the *depth bias* and `bench/depth_bias.py` uses it to get a
   measurement over 4.79 million pixels. It cannot do storey height: each scan publishes 7 to
   38 isolated frames sampled for training a depth model, not a continuous walk, so there is
   never enough coverage to reconstruct a room.

**What would measure it:** a venue known to be single-storey, with its full walk and its laser
cloud. Those venues exist — but identifying one requires downloading full captures to test,
and the cheap proxies for finding them do not work. The honest position is that G-CEIL is
unmeasured here, not that it passes.

**If it ever does run:** the laser side goes through *our* floor and ceiling fitting, not
Apple's annotations, so it measures our geometry against laser-grade depth and does not
revalidate the laser. A fitting error on noiseless input would cancel on both sides, which is
why the device-minus-laser difference is the number to report rather than either value alone.

    python bench/ceiling_vs_laser.py
"""
from __future__ import annotations

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
UP = ROOT / "data" / "arkitscenes_up" / "upsampling"
POSES = ROOT / "data" / "arkitscenes_up" / "poses" / "raw"
OUT = ROOT / "bench" / "results" / "ceiling_vs_laser.json"

DEPTH_MIN_M, DEPTH_MAX_M = 0.40, 5.00
PIXEL_STRIDE = 2
GATE_CEIL_M = 0.015          # G-CEIL: ceiling height within 1.5 cm


def read_traj(path: Path):
    rows = [l.split() for l in path.read_text().splitlines() if len(l.split()) >= 7]
    stamps = np.array([float(r[0]) for r in rows])
    poses = []
    for r in rows:
        T = np.eye(4)
        T[:3, :3] = Rotation.from_rotvec([float(r[1]), float(r[2]), float(r[3])]).as_matrix()
        T[:3, 3] = [float(r[4]), float(r[5]), float(r[6])]
        poses.append(T)
    return stamps, np.array(poses)


def fuse(scan: Path, pose_dir: Path, which: str) -> np.ndarray | None:
    """World-frame cloud from one depth source, using the capture's own poses."""
    traj = pose_dir / "lowres_wide.traj"
    intr_dir = pose_dir / "lowres_wide_intrinsics"
    if not traj.is_file() or not intr_dir.is_dir():
        return None
    stamps, poses = read_traj(traj)

    pts = []
    for f in sorted((scan / which).glob("*.png")):
        key = f.stem.split("_", 1)[1]
        t = float(key)
        j = int(np.argmin(np.abs(stamps - t)))
        if abs(stamps[j] - t) > 0.05:
            continue
        d = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
        if d is None:
            continue
        depth = d.astype(np.float32) / 1000.0

        cand = sorted(intr_dir.glob(f"*_{key}.pincam")) or sorted(intr_dir.glob(f"*{key[:key.find('.')]}*"))
        if not cand:
            continue
        iw, ih, fx, fy, cx, cy = (float(v) for v in cand[0].read_text().split())
        h, w = depth.shape
        sx, sy = w / iw, h / ih
        fx, fy = fx * sx, fy * sy
        cx, cy = (cx + 0.5) * sx - 0.5, (cy + 0.5) * sy - 0.5

        sub = depth[::PIXEL_STRIDE, ::PIXEL_STRIDE]
        v, u = np.mgrid[0:h:PIXEL_STRIDE, 0:w:PIXEL_STRIDE]
        keep = (sub > DEPTH_MIN_M) & (sub < DEPTH_MAX_M)
        if not keep.any():
            continue
        z = sub[keep]
        cam = np.stack([(u[keep] - cx) / fx * z, (v[keep] - cy) / fy * z, z], axis=1)
        pts.append(cam @ poses[j][:3, :3].T + poses[j][:3, 3])

    if not pts:
        return None
    P = np.vstack(pts)
    # Voxel-reduce to keep the height histogram comparable between the two sources.
    keys = np.floor(P / 0.02).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return P[np.sort(first)]


def storey(points: np.ndarray, cam_heights: np.ndarray):
    floor, ceiling = planes.floor_and_ceiling(points, cam_heights)
    if floor is None or ceiling is None:
        return None
    return planes.ceiling_height(floor, ceiling)[0], floor.height_m, ceiling.height_m


def main() -> int:
    scans = sorted(p for p in UP.glob("*/*") if p.is_dir() and (p / "highres_depth").is_dir())
    rows = []
    for scan in scans:
        pose_dir = POSES / scan.parent.name / scan.name
        dev = fuse(scan, pose_dir, "lowres_depth")
        las = fuse(scan, pose_dir, "highres_depth")
        if dev is None or las is None:
            print(f"  {scan.name}: no usable cloud (poses or intrinsics missing)")
            continue

        stamps, poses = read_traj(pose_dir / "lowres_wide.traj")
        cam = poses[:, 1, 3]
        sd, sl = storey(dev, cam), storey(las, cam)
        if sd is None or sl is None:
            print(f"  {scan.name}: no floor+ceiling pair visible "
                  f"(device {'ok' if sd else 'no'}, laser {'ok' if sl else 'no'})")
            rows.append({"scan": scan.name, "rejected": "no floor and ceiling both visible"})
            continue

        err = sd[0] - sl[0]
        rows.append({
            "scan": scan.name,
            "device_storey_m": sd[0], "laser_storey_m": sl[0],
            "error_mm": err * 1000,
            "within_gate": bool(abs(err) <= GATE_CEIL_M),
            "device_points": int(len(dev)), "laser_points": int(len(las)),
        })
        print(f"  {scan.name}: device {sd[0]:.3f} m  laser {sl[0]:.3f} m  "
              f"error {err*1000:+6.1f} mm  {'within 15 mm' if abs(err) <= GATE_CEIL_M else 'OUTSIDE'}")

    scored = [r for r in rows if "error_mm" in r]
    result = {
        "gate": "G-CEIL: ceiling height within 1.5 cm of truth",
        "method": "device depth and FARO-derived laser depth fused with the SAME poses, then "
                  "both run through our own floor/ceiling fit; the difference is reported",
        "caveat": "the laser side is run through our fitting, not Apple's annotations, so a "
                  "fitting error on noiseless input would cancel on both sides; this measures "
                  "our geometry against laser-grade depth, it does not revalidate the laser",
        "rows": rows,
        "scans_scored": len(scored),
        "scans_rejected": len(rows) - len(scored),
    }
    if scored:
        errs = np.array([r["error_mm"] for r in scored])
        within = sum(r["within_gate"] for r in scored)
        result.update({
            "within_gate": within, "total": len(scored),
            "median_error_mm": float(np.median(errs)),
            "max_abs_error_mm": float(np.abs(errs).max()),
            "gate_met": within == len(scored),
        })
        print(f"\n  G-CEIL: {within}/{len(scored)} scans within 15 mm   "
              f"median {np.median(errs):+.1f} mm   worst {np.abs(errs).max():.1f} mm")
        print(f"  gate {'MET' if within == len(scored) else 'NOT MET'}")
    else:
        print("\n  no scan had both a floor and a ceiling visible: NOT MEASURED")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
