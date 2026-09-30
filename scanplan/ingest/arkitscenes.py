"""ARKitScenes -> CaptureIR, and the laser-scanner ground truth beside it.

This is the only data in the benchmark with survey-grade truth attached: Apple published
iPad LiDAR walks alongside FARO Focus S70 scans of the same venues. Our own captures have no
truth at all -- nobody can tape-measure a flat they have never stood in -- so every absolute
accuracy claim the submission makes rests on this.

Layout:
    raw/<split>/<video_id>/lowres_depth/<video_id>_<timestamp>.png    uint16 mm
    raw/<split>/<video_id>/confidence/...                            uint8 0..2
    raw/<split>/<video_id>/lowres_wide/...                           RGB
    raw/<split>/<video_id>/lowres_wide_intrinsics/...                one file per frame
    raw/<split>/<video_id>/lowres_wide.traj                          timestamp + pose per line
    laser_scanner_point_clouds/<visit_id>/<id>.ply                   the reference
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from ..detect import CaptureError
from ..ir import CaptureIR, Frame, Intrinsics, ScaleEstimate

cv2.setNumThreads(0)


def _read_traj(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """ARKitScenes trajectory: timestamp, then a rotation vector and a translation."""
    rows = [l.split() for l in path.read_text().splitlines() if l.strip()]
    stamps = np.array([float(r[0]) for r in rows])
    poses = np.zeros((len(rows), 4, 4))
    for i, r in enumerate(rows):
        rvec = np.array([float(r[1]), float(r[2]), float(r[3])])
        tvec = np.array([float(r[4]), float(r[5]), float(r[6])])
        poses[i] = np.eye(4)
        poses[i, :3, :3] = Rotation.from_rotvec(rvec).as_matrix()
        poses[i, :3, 3] = tvec
    return stamps, poses


def _stamp(p: Path) -> str:
    return p.stem.split("_", 1)[1]


def load(path, *, stride: int = 3, max_frames: int | None = None) -> CaptureIR:
    path = Path(path)
    vid = path.name
    depth_dir, conf_dir = path / "lowres_depth", path / "confidence"
    intr_dir, traj_file = path / "lowres_wide_intrinsics", path / "lowres_wide.traj"
    for p in (depth_dir, intr_dir, traj_file):
        if not p.exists():
            raise CaptureError(f"{path}: not an ARKitScenes raw scan, missing {p.name}")

    stamps, poses = _read_traj(traj_file)
    depth_files = {_stamp(f): f for f in sorted(depth_dir.glob("*.png"))}

    ir = CaptureIR(capture_id=vid, tier="lidar",
                   scale=ScaleEstimate(1.0, 0.0, "lidar_depth", "iPad Pro LiDAR, metric"))

    keys = sorted(depth_files)[::stride]
    if max_frames:
        keys = keys[:max_frames]

    unreadable = 0
    for key in keys:
        # Match the nearest trajectory entry; ARKitScenes timestamps are not exactly equal.
        t = float(key)
        j = int(np.argmin(np.abs(stamps - t)))
        if abs(stamps[j] - t) > 0.05:
            continue

        img = cv2.imread(str(depth_files[key]), cv2.IMREAD_UNCHANGED)
        if img is None:
            unreadable += 1
            continue
        depth = img.astype(np.float32) / 1000.0
        h, w = depth.shape

        intr_path = intr_dir / f"{vid}_{key}.pincam"
        if not intr_path.is_file():
            cands = sorted(intr_dir.glob(f"{vid}_{key[:key.find('.')]}*"))
            if not cands:
                continue
            intr_path = cands[0]
        iw, ih, fx, fy, cx, cy = (float(v) for v in intr_path.read_text().split())

        conf_path = conf_dir / f"{vid}_{key}.png"
        conf = cv2.imread(str(conf_path), cv2.IMREAD_UNCHANGED) if conf_path.is_file() else None

        ir.frames.append(Frame(
            index=len(ir.frames), timestamp=t,
            intrinsics=Intrinsics(fx, fy, cx, cy, int(iw), int(ih)).scaled_to(w, h),
            world_from_cam=poses[j], depth_m=depth, depth_confidence=conf,
        ))

    if not ir.frames:
        raise CaptureError(f"{path}: no usable frames")
    if unreadable:
        ir.warnings.append(f"{unreadable} depth frames could not be decoded and were skipped")
    return ir


def laser_levels(ply_path, *, max_points: int = 4_000_000) -> np.ndarray:
    """Read a FARO point cloud, returning (n, 3) in metres.

    These files are ~1.9 GB of ASCII or binary PLY, so the reader streams and subsamples
    rather than loading the lot: only the height distribution is needed to locate floor and
    ceiling, and four million points settle that to well under a millimetre.
    """
    path = Path(ply_path)
    with path.open("rb") as f:
        fmt, count, props, in_vertex, offset = None, 0, [], False, 0
        while True:
            raw = f.readline()
            offset += len(raw)
            line = raw.decode("ascii", "replace").strip()
            if line.startswith("format"):
                fmt = line.split()[1]
            elif line.startswith("element"):
                # Only the vertex element's properties describe the record we want; these
                # files carry a trailing `element face` whose `property list` is a different
                # shape entirely and must not join the vertex dtype.
                parts = line.split()
                in_vertex = parts[1] == "vertex"
                if in_vertex:
                    count = int(parts[2])
            elif line.startswith("property") and in_vertex:
                props.append(line.split())
            elif line == "end_header":
                break

        if fmt == "ascii":
            step = max(count // max_points, 1)
            pts = []
            for i, line in enumerate(f):
                if i % step:
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    pts.append((float(parts[0]), float(parts[1]), float(parts[2])))
            return np.asarray(pts, dtype=np.float64)

        # Binary: build the vertex dtype from the declared properties.
        np_of = {"float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
                 "uchar": "u1", "uint8": "u1", "char": "i1", "int8": "i1",
                 "ushort": "u2", "uint16": "u2", "short": "i2", "int16": "i2",
                 "uint": "u4", "uint32": "u4", "int": "i4", "int32": "i4"}
        endian = "<" if "little" in fmt else ">"
        dtype = np.dtype([(pr[2], endian + np_of[pr[1]]) for pr in props])
    # Memory-map rather than read: these clouds are 1.9 GB and only every nth height is
    # needed, so pulling the whole file through RAM would cost more than the measurement.
    data = np.memmap(path, dtype=dtype, mode="r", offset=offset, shape=(count,))
    step = max(count // max_points, 1)
    sub = data[::step]
    return np.stack([np.asarray(sub["x"]), np.asarray(sub["y"]), np.asarray(sub["z"])],
                    axis=1).astype(np.float64)
