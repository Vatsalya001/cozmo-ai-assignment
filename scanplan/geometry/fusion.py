"""Depth frames -> one gravity-aligned metric point cloud.

Back-projection uses the OpenCV camera convention (x right, y down, z forward) and the
per-frame intrinsics, because fx varies by up to 2.1% within a single capture.

Memory matters here: 3250 kept frames at 256x192 is 160 million points, which is why pixels
are subsampled and the result is voxel-reduced in one pass rather than accumulated whole.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..ir import CaptureIR

DEPTH_MIN_M = 0.25          # closer than this is the phone seeing itself or noise
DEPTH_MAX_M = 5.0           # iPhone LiDAR degrades badly past ~5 m
VOXEL_M = 0.02              # 2 cm: below the accuracy we are chasing, above the noise floor

# OpenCV spawns its own worker pool; nested against NumPy's BLAS threads it is a known
# source of intermittent native crashes, and one unexplained segfault was seen here on the
# largest capture. Decoding one small PNG gains nothing from threading, so it is turned off.
cv2.setNumThreads(0)


def _backproject(frame, pixel_stride: int, min_confidence: int) -> np.ndarray:
    depth = frame.depth_m[::pixel_stride, ::pixel_stride]
    K = frame.intrinsics.scaled_to(frame.depth_m.shape[1], frame.depth_m.shape[0])

    v, u = np.mgrid[0:frame.depth_m.shape[0]:pixel_stride, 0:frame.depth_m.shape[1]:pixel_stride]
    keep = (depth > DEPTH_MIN_M) & (depth < DEPTH_MAX_M)
    if frame.depth_confidence is not None:
        keep &= frame.depth_confidence[::pixel_stride, ::pixel_stride] >= min_confidence
    if not keep.any():
        return np.zeros((0, 3))

    d = depth[keep]
    cam = np.stack([(u[keep] - K.cx) / K.fx * d, (v[keep] - K.cy) / K.fy * d, d], axis=1)
    return cam @ frame.rotation.T + frame.position


def voxel_reduce(points: np.ndarray, voxel_m: float = VOXEL_M) -> np.ndarray:
    """One representative point per occupied voxel. Keeps the first point in each voxel
    rather than the centroid: centroids of a voxel straddling two surfaces invent geometry
    that was never measured."""
    if len(points) == 0:
        return points
    keys = np.floor(points / voxel_m).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return points[np.sort(first)]


def fuse(ir: CaptureIR, *, pixel_stride: int = 2, min_confidence: int = 1,
         voxel_m: float = VOXEL_M, release_depth: bool = True) -> CaptureIR:
    """Populate ir.points.

    Voxel-reduces every 200 frames so peak memory stays bounded, and by default releases each
    frame's depth and confidence rasters once consumed. On the largest supplied capture those
    rasters are 0.9 GB that nothing downstream reads, and the walk-in test is a live cold run
    on a machine whose spare memory we do not get to choose.
    """
    chunks: list[np.ndarray] = []
    pending: list[np.ndarray] = []

    for n, frame in enumerate(ir.frames, 1):
        if frame.depth_m is None:
            continue
        pending.append(_backproject(frame, pixel_stride, min_confidence))
        if release_depth:
            frame.depth_m = None
            frame.depth_confidence = None
        if n % 200 == 0:
            chunks.append(voxel_reduce(np.vstack(pending), voxel_m))
            pending = []

    if pending:
        chunks.append(voxel_reduce(np.vstack(pending), voxel_m))
    ir.points = voxel_reduce(np.vstack(chunks), voxel_m) if chunks else np.zeros((0, 3))
    return ir
