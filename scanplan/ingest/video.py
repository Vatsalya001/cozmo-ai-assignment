"""Video tier: RGB frames and VIO poses, with depth from a monocular model.

## What this tier is, precisely

An iPhone 15 non-Pro has **no depth sensor** but **does run ARKit**, so a capture app on that
device records RGB and a gravity-aligned VIO pose track and no depth at all. That is the gap
this tier fills: poses from the phone's own tracking, depth from a model.

Depth has to be inferred because it was never measured, and scale is mathematically
unobservable from monocular images — a dollhouse and a room project identically. A *metric*
depth model is used rather than a relative one for exactly that reason: relative depth would
leave the plan correct in shape and unknown in size, which is not a floor plan.

## Why this is not the LiDAR tier wearing a disguise

The captures available carry LiDAR depth, and this tier **ignores it entirely** — only
`rgb.mp4` and the pose track are read. That makes the comparison against the LiDAR tier on the
same capture a genuine measurement of what is lost when the depth sensor goes away, which is
the number this tier exists to report.

The pose track is the one thing taken from the capture rather than inferred. On a real iPhone
15 that track comes from ARKit through the capture app named in the capture protocol; it is
not a LiDAR product and needs no depth sensor. Estimating poses from the video alone is a
different and much larger problem, and pretending otherwise would put an unvalidated
structure-from-motion stage underneath every number this tier reports.
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from ..detect import CaptureError
from ..ir import CaptureIR, Frame, Intrinsics, ScaleEstimate

cv2.setNumThreads(0)

MODEL = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
KEYFRAMES = 120             # ~1.8 min of CPU inference; see A-RUNTIME in docs/gates.md
DEPTH_W, DEPTH_H = 256, 192  # matched to the LiDAR tier so the geometry core sees one shape
DEPTH_MAX_M = 8.0

_pipe = None


def _depth_model():
    """Load the metric depth model, or say plainly what is missing.

    The default install is `pip install -e ".[dev]"`, which deliberately omits torch and
    transformers so the LiDAR tier needs no weights and no network. A clean-clone check caught
    the consequence: asking for the video or photo tier on that install raised a bare
    ModuleNotFoundError. On walk-in day that is a traceback in front of the examiners, where a
    stated failure naming the fix is worth far more.
    """
    global _pipe
    if _pipe is None:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        try:
            from transformers import pipeline as hf_pipeline
        except ImportError as e:
            raise CaptureError(
                "the video and photo tiers need the model extra, which the default install "
                "omits so the LiDAR tier stays weight-free and offline. Install it with:\n"
                '    pip install -e ".[dev,models]"\n'
                "then re-run. The LiDAR tier works without it.") from e
        _pipe = hf_pipeline(task="depth-estimation", model=MODEL, device="cpu")
    return _pipe


def _read_poses(folder: Path):
    """Gravity-aligned VIO poses recorded alongside the video by the capture app."""
    odo = pd.read_csv(folder / "odometry.csv", skipinitialspace=True)
    odo.columns = [c.strip() for c in odo.columns]
    return (odo["timestamp"].to_numpy(float),
            odo[["x", "y", "z"]].to_numpy(float),
            Rotation.from_quat(odo[["qx", "qy", "qz", "qw"]].to_numpy(float)),
            odo[["fx", "fy", "cx", "cy"]].to_numpy(float))


def load(path, *, keyframes: int = KEYFRAMES, progress: bool = False) -> CaptureIR:
    """Build a CaptureIR from RGB plus VIO poses. Depth is inferred, never read."""
    path = Path(path)
    folder = path if path.is_dir() else path.parent
    video = path if path.is_file() else folder / "rgb.mp4"
    if not video.is_file():
        raise CaptureError(f"{path}: no video found")
    if not (folder / "odometry.csv").is_file():
        raise CaptureError(
            f"{folder}: the video tier needs a pose track recorded alongside the clip "
            f"(odometry.csv). A bare .mov carries no poses, and estimating them from the video "
            f"alone is structure-from-motion, which this pipeline does not implement")

    stamps, positions, rotations, K = _read_poses(folder)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise CaptureError(f"{video}: cannot be opened")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        raise CaptureError(f"{video}: reports no frames")

    picks = np.linspace(0, total - 1, min(keyframes, total)).astype(int)
    model = _depth_model()

    ir = CaptureIR(
        capture_id=folder.name, tier="video",
        scale=ScaleEstimate(1.0, 0.05, "metric_depth_model",
                            f"{MODEL}; metric by construction, not by observation"))

    from PIL import Image
    kept = 0
    for n, idx in enumerate(picks):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, bgr = cap.read()
        if not ok:
            continue

        # Map frame index to the pose track by proportion of the way through the capture.
        j = min(int(round(idx / max(total - 1, 1) * (len(stamps) - 1))), len(stamps) - 1)

        small = cv2.resize(bgr, (DEPTH_W * 2, DEPTH_H * 2), interpolation=cv2.INTER_AREA)
        out = model(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
        depth = np.asarray(out["predicted_depth"] if "predicted_depth" in out else out["depth"],
                           dtype=np.float32)
        if depth.shape != (DEPTH_H, DEPTH_W):
            depth = cv2.resize(depth, (DEPTH_W, DEPTH_H), interpolation=cv2.INTER_NEAREST)
        depth[(depth <= 0) | (depth > DEPTH_MAX_M)] = 0.0

        T = np.eye(4)
        T[:3, :3] = rotations[j].as_matrix()
        T[:3, 3] = positions[j]

        fx, fy, cx, cy = K[j]
        ir.frames.append(Frame(
            index=int(idx), timestamp=float(stamps[j]),
            intrinsics=Intrinsics(fx, fy, cx, cy, 1920, 1440).scaled_to(DEPTH_W, DEPTH_H),
            world_from_cam=T, depth_m=depth, depth_confidence=None))
        kept += 1
        if progress and n % 20 == 0:
            print(f"  video tier: {n}/{len(picks)} keyframes", flush=True)

    cap.release()
    if not ir.frames:
        raise CaptureError(f"{video}: no frame could be decoded")

    ir.warnings.append(
        f"video tier: depth for {kept} keyframes is INFERRED by {MODEL.split('/')[-1]}, not "
        f"measured. Scale is unobservable from monocular images, so it comes from the model's "
        f"metric training rather than from this room. Intervals are widened accordingly")
    return ir
