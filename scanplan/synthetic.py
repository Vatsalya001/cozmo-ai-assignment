"""Generate a Stray Scanner capture of a room whose size is known exactly.

Every accuracy claim that rests on external data shares one weakness: when the pipeline and the
reference disagree, the data cannot tell you which is wrong. A room built from an equation can.
Its walls are 4.00 and 3.00 m because we made them so, and if the pipeline reports something
else, the pipeline is wrong.

The output is a **real Stray Scanner export** -- same directory layout, same uint16 millimetre
depth, same odometry CSV -- so the actual loader is exercised rather than a mock of it, and any
other pipeline that reads the public format can read it too. That last property is what makes
`bench/head_to_head_engineer.py` possible: two independent implementations, one input, exact
truth.

This lives in the package rather than in `tests/` because a benchmark needs it and a benchmark
importing from the test suite is the wrong direction. `tests/conftest.py` wraps it in fixtures.

## Two things this fixture models deliberately

**Depth is written 18 mm SHORT**, because that is what the device was measured to do
(`bench/depth_bias.py`, 4.79 M pixels against FARO laser truth). Handing the loader unbiased
depth would let it add 18 mm anyway, producing a room 18 mm too large while appearing to
validate the correction.

**The pitch sweeps smoothly and the walk is long.** Both were bugs. The pitch used to cycle with
period 3 (`sweep[i % 3]`) and the pipeline's default stride is also 3, so `scanplan run` sampled
one pitch forever, saw no floor, and failed on the capture this project generates to validate
itself -- while every test passed, because they all load at stride 1. The walk was then 180
frames, leaving 60 after stride 3: too few floor-facing views to cover the floor, and area read
-62% at stride 3 against -2.7% at stride 1. Real captures carry 1,715 to 9,745 frames.

Both fixes point the same way: a fixture used to validate accuracy must give the same answer at
every stride, because stride decides how many frames are kept and not how big the room is.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

cv2.setNumThreads(0)

RGB_W, RGB_H = 1920, 1440
FX = FY = 1600.0
CX, CY = 959.5, 719.5
DEPTH_W, DEPTH_H = 256, 192
CAMERA_HEIGHT_M = 1.50

# Measured, not assumed: bench/depth_bias.py, 8 scans, 4.79 million pixels.
DEVICE_BIAS_M = 0.018

PITCH_AMPLITUDE_DEG = 42.0
SWEEP_CYCLES = 11          # coprime with any plausible stride
DEFAULT_FRAMES = 360       # stride-independent: -3.0%, -2.5%, -2.4% at strides 1, 3, 5


def depth_intrinsics():
    sx, sy = DEPTH_W / RGB_W, DEPTH_H / RGB_H
    return FX * sx, FY * sy, (CX + 0.5) * sx - 0.5, (CY + 0.5) * sy - 0.5


def _look(direction_xz, pitch_deg):
    """world_from_cam for OpenCV camera axes (x right, y down, z forward), world y up."""
    fwd = np.array([direction_xz[0], 0.0, direction_xz[1]], float)
    fwd /= np.linalg.norm(fwd)
    right = np.cross([0.0, 1.0, 0.0], fwd)
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    R = np.column_stack([right, down, fwd])
    return R @ Rotation.from_euler("x", pitch_deg, degrees=True).as_matrix()


def _exit_depth(R, pos, room):
    """Depth at every pixel, by exiting an axis-aligned box from inside."""
    fx, fy, cx, cy = depth_intrinsics()
    u, v = np.meshgrid(np.arange(DEPTH_W), np.arange(DEPTH_H))
    dirs = np.stack([(u - cx) / fx, (v - cy) / fy, np.ones_like(u, float)], -1)
    world = dirs @ R.T
    t = np.full(world.shape[:2], np.inf)
    for axis, key in enumerate("xyz"):
        lo, hi = room[key]
        d = world[..., axis]
        with np.errstate(divide="ignore", invalid="ignore"):
            hit = np.where(d > 0, (hi - pos[axis]) / d, (lo - pos[axis]) / d)
        t = np.minimum(t, np.where(np.abs(d) < 1e-9, np.inf, hit))
    return t                      # dirs[..., 2] == 1, so t is the camera-frame z


def write_stray_capture(out_dir, *, width_m: float = 4.0, depth_m: float = 3.0,
                        ceiling_m: float = 2.5, frames: int = DEFAULT_FRAMES,
                        device_bias_m: float = DEVICE_BIAS_M) -> dict:
    """A box room walked as a loop, facing outward, pitch sweeping floor to ceiling.

    `device_bias_m` is subtracted from true depth, modelling a sensor that reads short. Pass 0.0
    for an ideal sensor -- `bench/head_to_head_engineer.py` uses both, because whether the
    synthetic sensor is biased decides which pipeline wins, and that is the finding.

    Returns the truth: the dimensions the capture was built from.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "depth").mkdir(exist_ok=True)
    (out_dir / "confidence").mkdir(exist_ok=True)
    room = {"x": (0.0, width_m), "y": (0.0, ceiling_m), "z": (0.0, depth_m)}

    (out_dir / "camera_matrix.csv").write_text(
        f"{FX}, 0.0, {CX}\n0.0, {FY}, {CY}\n0.0, 0.0, 1.0\n")
    (out_dir / "imu.csv").write_text("timestamp, a_x, a_y, a_z, alpha_x, alpha_y, alpha_z\n"
                                     "100.0, 0.0, -9.81, 0.0, 0.0, 0.0, 0.0\n")

    inset = 1.0
    corners = np.array([[inset, inset], [width_m - inset, inset],
                        [width_m - inset, depth_m - inset], [inset, depth_m - inset]])
    centre = np.array([width_m / 2, depth_m / 2])

    rows = ["timestamp, frame, x, y, z, qx, qy, qz, qw, fx, fy, cx, cy"]
    writer = cv2.VideoWriter(str(out_dir / "rgb.mp4"),
                             cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (RGB_W, RGB_H))
    grey = np.full((RGB_H, RGB_W, 3), 128, np.uint8)

    for i in range(frames):
        s = 4.0 * i / frames
        a, b = corners[int(s) % 4], corners[(int(s) + 1) % 4]
        xz = a + (b - a) * (s - int(s))
        outward = xz - centre
        outward /= np.linalg.norm(outward)
        pos = np.array([xz[0], CAMERA_HEIGHT_M, xz[1]])
        pitch = PITCH_AMPLITUDE_DEG * np.sin(2 * np.pi * SWEEP_CYCLES * i / frames)
        R = _look(outward, pitch)

        biased = _exit_depth(R, pos, room) - device_bias_m
        cv2.imwrite(str(out_dir / "depth" / f"{i:06d}.png"),
                    np.clip(biased * 1000.0, 0, 65535).astype(np.uint16))
        cv2.imwrite(str(out_dir / "confidence" / f"{i:06d}.png"),
                    np.full((DEPTH_H, DEPTH_W), 2, np.uint8))
        q = Rotation.from_matrix(R).as_quat()
        rows.append(f"{100 + i / 30:.6f}, {i:06d}, {pos[0]:.6f}, {pos[1]:.6f}, {pos[2]:.6f}, "
                    f"{q[0]:.6f}, {q[1]:.6f}, {q[2]:.6f}, {q[3]:.6f}, {FX}, {FY}, {CX}, {CY}")
        writer.write(grey)

    writer.release()
    (out_dir / "odometry.csv").write_text("\n".join(rows) + "\n")
    return {"path": out_dir, "width_m": width_m, "depth_m": depth_m,
            "ceiling_m": ceiling_m, "area_m2": width_m * depth_m,
            "perimeter_m": 2 * (width_m + depth_m), "frames": frames,
            "device_bias_m": device_bias_m}
