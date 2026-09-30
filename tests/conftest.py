"""Synthetic captures with exactly known geometry.

Every accuracy claim elsewhere in this project rests on external data, and external data
cannot tell you whether a bug is in your pipeline or in the capture. A room built from an
equation can: its walls are 4.00 and 3.00 m because we made them so, and if the pipeline
reports something else the pipeline is wrong.

The generator writes a real Stray Scanner export -- same directory layout, same uint16
millimetre depth, same odometry CSV -- so the tests exercise the actual loader rather than a
mock of it.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

import cv2

cv2.setNumThreads(0)

RGB_W, RGB_H = 1920, 1440
FX = FY = 1600.0
CX, CY = 959.5, 719.5
DEPTH_W, DEPTH_H = 256, 192
CAMERA_HEIGHT_M = 1.50


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


def write_stray_capture(out_dir, *, width_m=4.0, depth_m=3.0, ceiling_m=2.5, frames=180):
    """A box room walked as a loop, facing outward, sweeping floor / walls / ceiling."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "depth").mkdir(exist_ok=True)
    (out_dir / "confidence").mkdir(exist_ok=True)
    room = {"x": (0.0, width_m), "y": (0.0, ceiling_m), "z": (0.0, depth_m)}

    (out_dir / "camera_matrix.csv").write_text(f"{FX}, 0.0, {CX}\n0.0, {FY}, {CY}\n0.0, 0.0, 1.0\n")
    (out_dir / "imu.csv").write_text("timestamp, a_x, a_y, a_z, alpha_x, alpha_y, alpha_z\n"
                                     "100.0, 0.0, -9.81, 0.0, 0.0, 0.0, 0.0\n")

    inset = 1.0
    corners = np.array([[inset, inset], [width_m - inset, inset],
                        [width_m - inset, depth_m - inset], [inset, depth_m - inset]])
    centre = np.array([width_m / 2, depth_m / 2])
    sweep = [-40.0, 0.0, 35.0]                    # floor, walls, ceiling

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
        R = _look(outward, sweep[i % 3])

        cv2.imwrite(str(out_dir / "depth" / f"{i:06d}.png"),
                    np.clip(_exit_depth(R, pos, room) * 1000.0, 0, 65535).astype(np.uint16))
        cv2.imwrite(str(out_dir / "confidence" / f"{i:06d}.png"),
                    np.full((DEPTH_H, DEPTH_W), 2, np.uint8))
        q = Rotation.from_matrix(R).as_quat()
        rows.append(f"{100 + i / 30:.6f}, {i:06d}, {pos[0]:.6f}, {pos[1]:.6f}, {pos[2]:.6f}, "
                    f"{q[0]:.6f}, {q[1]:.6f}, {q[2]:.6f}, {q[3]:.6f}, {FX}, {FY}, {CX}, {CY}")
        writer.write(grey)

    writer.release()
    (out_dir / "odometry.csv").write_text("\n".join(rows) + "\n")
    return {"path": out_dir, "width_m": width_m, "depth_m": depth_m,
            "ceiling_m": ceiling_m, "area_m2": width_m * depth_m, "frames": frames}


@pytest.fixture(scope="session")
def synthetic_room(tmp_path_factory):
    """A 4.00 x 3.00 m room, 2.50 m ceiling. Built once; the tests only read it."""
    return write_stray_capture(tmp_path_factory.mktemp("synthetic") / "box_room")


@pytest.fixture(scope="session")
def synthetic_ir(synthetic_room):
    from scanplan.geometry import fusion
    from scanplan.ingest import stray
    ir = stray.load(synthetic_room["path"], stride=1)
    fusion.fuse(ir)
    return ir
