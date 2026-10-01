"""Stray Scanner export -> CaptureIR (the LiDAR tier).

Folder layout (https://docs.strayrobots.io/apps/scanner/format.html):
    rgb.mp4                HEVC video, 1920x1440
    depth/NNNNNN.png       uint16 depth in millimetres, 256x192
    confidence/NNNNNN.png  uint8: 0 low, 1 medium, 2 high
    odometry.csv           per frame: timestamp, frame, x, y, z, qx, qy, qz, qw, fx, fy, cx, cy
    imu.csv                accelerometer and gyroscope
    camera_matrix.csv      intrinsics

Conventions measured on the supplied captures (see bench/probe_captures.py):

- The odometry pose maps OpenCV camera axes (x right, y down, z forward) into a
  gravity-aligned world with **y up**. The origin is the camera's starting pose, not the
  floor, so the floor height is unknown until it is fitted from the depth.
- Intrinsics in odometry.csv are **per frame** and refer to the RGB image. fx varies by up to
  2.1% within a single capture, so the per-frame values are always used and camera_matrix.csv
  is read only as a fallback.
- Depth is 256x192 while the intrinsics describe 1920x1440, so they are rescaled per frame.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from ..detect import CaptureError
from ..ir import CaptureIR, Frame, Intrinsics, ScaleEstimate

ODOMETRY_COLUMNS = ["timestamp", "frame", "x", "y", "z", "qx", "qy", "qz", "qw", "fx", "fy", "cx", "cy"]
RGB_SIZE = (1920, 1440)
POSE_JUMP_M = 0.10          # a normal step at 60 fps is under 3 cm
MIN_CONFIDENCE = 1          # 0 low, 1 medium, 2 high; low returns are dropped

# Measured, not assumed: the device reads 18 mm SHORT of FARO laser truth, pooled over
# 4.79 million pixels across 8 ARKitScenes scans where laser depth is registered to the same
# frames (bench/depth_bias.py). Adding it back is the whole correction; the 4 mm that the
# scan-to-scan spread leaves unexplained stays in the interval instead.
DEPTH_BIAS_CORRECTION_M = 0.018


class StrayCapture:
    """Lazy reader. Depth frames are only decoded when asked for, so a 9745-frame capture
    can be inspected without loading 531 MB."""

    def __init__(self, path):
        self.path = Path(path)
        self.warnings: list[str] = []

        missing = [n for n in ("odometry.csv", "camera_matrix.csv") if not (self.path / n).is_file()]
        missing += [n + "/" for n in ("depth", "confidence") if not (self.path / n).is_dir()]
        if missing:
            raise CaptureError(f"{self.path}: incomplete Stray Scanner export, missing {', '.join(missing)}")

        odo = pd.read_csv(self.path / "odometry.csv", skipinitialspace=True)
        odo.columns = [c.strip() for c in odo.columns]
        lacking = [c for c in ODOMETRY_COLUMNS if c not in odo.columns]
        if lacking:
            raise CaptureError(f"odometry.csv is missing columns: {', '.join(lacking)}")
        if odo.empty:
            raise CaptureError("odometry.csv has no frames")
        if odo[ODOMETRY_COLUMNS].isna().any().any():
            raise CaptureError("odometry.csv has empty pose or intrinsics values")

        self.timestamps = odo["timestamp"].to_numpy(float)
        self.frame_ids = odo["frame"].to_numpy(int)
        self.positions = odo[["x", "y", "z"]].to_numpy(float)
        self._rotations = Rotation.from_quat(odo[["qx", "qy", "qz", "qw"]].to_numpy(float))
        self._rgb_k = odo[["fx", "fy", "cx", "cy"]].to_numpy(float)

        if np.any(np.diff(self.timestamps) <= 0):
            raise CaptureError("odometry.csv timestamps are not strictly increasing")

    def __len__(self) -> int:
        return len(self.timestamps)

    # ---- per-frame accessors ----------------------------------------------------------
    def _png(self, kind: str, i: int) -> np.ndarray:
        f = self.path / kind / f"{int(self.frame_ids[i]):06d}.png"
        img = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise CaptureError(f"cannot read {kind}/{f.name}")
        return img

    def depth_m(self, i: int) -> np.ndarray:
        d = self._png("depth", i).astype(np.float32) / 1000.0
        d[d > 0] += DEPTH_BIAS_CORRECTION_M      # see DEPTH_BIAS_CORRECTION_M
        return d

    def confidence(self, i: int) -> np.ndarray:
        return self._png("confidence", i)

    def intrinsics(self, i: int, width: int, height: int) -> Intrinsics:
        fx, fy, cx, cy = self._rgb_k[i]
        return Intrinsics(fx, fy, cx, cy, *RGB_SIZE).scaled_to(width, height)

    def world_from_cam(self, i: int) -> np.ndarray:
        T = np.eye(4)
        T[:3, :3] = self._rotations[i].as_matrix()
        T[:3, 3] = self.positions[i]
        return T

    # ---- capture-level diagnostics ----------------------------------------------------
    def pose_jumps(self, threshold_m: float = POSE_JUMP_M) -> list[tuple[int, float]]:
        """Frames where tracking discontinuously relocalised. These are real: 1a8384c3f6
        contains a 31 cm jump at 60 fps, which no walking pace can produce."""
        step = np.linalg.norm(np.diff(self.positions, axis=0), axis=1)
        return [(int(i + 1), float(d)) for i, d in enumerate(step) if d > threshold_m]

    def loop_closed(self, threshold_m: float = 1.0) -> bool:
        return bool(np.linalg.norm(self.positions[-1] - self.positions[0]) < threshold_m)

    def summary(self) -> dict:
        step = np.linalg.norm(np.diff(self.positions, axis=0), axis=1)
        d0 = self.depth_m(0)
        return {
            "frames": len(self),
            "duration_s": round(float(self.timestamps[-1] - self.timestamps[0]), 1),
            "fps": round(float(1.0 / np.median(np.diff(self.timestamps))), 1),
            "path_length_m": round(float(step.sum()), 2),
            "start_to_end_m": round(float(np.linalg.norm(self.positions[-1] - self.positions[0])), 3),
            "loop_closed": self.loop_closed(),
            "pose_jumps": self.pose_jumps(),
            "depth_size": [int(d0.shape[1]), int(d0.shape[0])],
            "fx_variation_pct": round(float((self._rgb_k[:, 0].max() / self._rgb_k[:, 0].min() - 1) * 100), 2),
        }


def load(path, *, stride: int = 3) -> CaptureIR:
    """Read a capture into the IR, keeping every `stride`-th frame.

    At 60 fps consecutive frames are near-duplicates: stride 3 keeps 20 fps, which is ample
    for geometry and cuts a 214 s walk from 9745 frames to about 3250. Runtime is a scored
    gate (A-RUNTIME), so the default is set here rather than left to each caller.
    """
    cap = StrayCapture(path)
    ir = CaptureIR(capture_id=Path(path).name, tier="lidar",
                   scale=ScaleEstimate(1.0, 0.0, "lidar_depth", "device LiDAR, metric by construction"))

    unreadable = []
    for i in range(0, len(cap), stride):
        try:
            depth = cap.depth_m(i)
            conf = cap.confidence(i)
        except CaptureError:
            # A frame that will not decode is dropped, not fatal. At 60 fps its neighbours
            # cover the same surfaces, and the walk-in test is a live cold run on someone
            # else's capture -- refusing to produce a plan because one frame of nine thousand
            # is damaged would be the wrong trade every time.
            unreadable.append(i)
            continue
        h, w = depth.shape
        ir.frames.append(Frame(
            index=i,
            timestamp=float(cap.timestamps[i]),
            intrinsics=cap.intrinsics(i, w, h),
            world_from_cam=cap.world_from_cam(i),
            depth_m=depth,
            depth_confidence=conf,
        ))

    if unreadable:
        ir.warnings.append(
            f"{len(unreadable)} of {len(range(0, len(cap), stride))} sampled depth frames "
            f"could not be decoded and were skipped (first: {unreadable[0]})")
    if not ir.frames:
        raise CaptureError(f"{path}: no depth frame could be decoded")

    jumps = cap.pose_jumps()
    if jumps:
        ir.warnings.append(
            f"tracking relocalised {len(jumps)} time(s) (largest {max(d for _, d in jumps)*100:.0f} cm); "
            f"geometry either side of a jump may not line up")
    if not cap.loop_closed():
        ir.warnings.append(
            f"the walk did not return to its start ({np.linalg.norm(cap.positions[-1]-cap.positions[0]):.2f} m apart); "
            f"drift correction has no loop to close, so accumulated error cannot be removed")
    return ir
