"""Drift correction: submaps, loop closures and a 4-DoF pose graph.

ARKit's tracking is good locally and wanders globally. Over a 100 m walk the heading creeps
by a degree or two, which puts the far end of a flat half a metre from where it belongs and
smears every wall it touches.

Only four degrees of freedom are corrected. Gravity is measured directly by the IMU and is
not in doubt, so roll and pitch are left alone; what drifts is position and heading about the
vertical. Optimising the two that are already right would only let the solver trade real
error against imaginary error.

Loop closures come from revisits: two moments far apart in the walk that are close in space
are almost certainly the same place, and the distance between them is drift made visible.
A walk that never revisits anywhere has nothing to close, which the report must say rather
than quietly reporting a correction of zero as a success.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from ..ir import CaptureIR

SUBMAP_SECONDS = 8.0        # a stretch short enough to be internally rigid
REVISIT_RADIUS_M = 1.5      # how close two moments must be to count as the same place
REVISIT_MIN_GAP_S = 12.0    # and how far apart in time, so neighbours do not count
ODOMETRY_WEIGHT = 30.0      # trust in ARKit between submaps, relative to a loop closure


@dataclass
class DriftReport:
    method: str
    submaps: int
    loop_closures: int
    applied: bool
    max_shift_m: float = 0.0
    mean_shift_m: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"method": self.method, "loop_closures": self.loop_closures,
                "applied": self.applied, "submaps": self.submaps,
                "max_shift_m": round(self.max_shift_m, 4),
                "mean_shift_m": round(self.mean_shift_m, 4),
                "notes": self.notes}


def _submap_of(timestamps: np.ndarray, seconds: float) -> np.ndarray:
    return ((timestamps - timestamps[0]) // seconds).astype(int)


def find_loop_closures(positions: np.ndarray, timestamps: np.ndarray, submap: np.ndarray,
                       *, radius_m: float = REVISIT_RADIUS_M,
                       min_gap_s: float = REVISIT_MIN_GAP_S) -> list[tuple[int, int, np.ndarray]]:
    """Pairs of submaps that revisit the same place, and the offset between them."""
    xz = positions[:, [0, 2]]
    pairs: dict[tuple[int, int], list] = {}

    for i in range(len(xz)):
        d = np.linalg.norm(xz[i + 1:] - xz[i], axis=1)
        dt = timestamps[i + 1:] - timestamps[i]
        hit = np.nonzero((d < radius_m) & (dt > min_gap_s))[0]
        for j in hit + i + 1:
            a, b = submap[i], submap[j]
            if a == b:
                continue
            pairs.setdefault((min(a, b), max(a, b)), []).append(xz[j] - xz[i])

    return [(a, b, np.median(np.asarray(v), axis=0)) for (a, b), v in pairs.items()]


def correct(ir: CaptureIR, *, apply: bool = True,
            submap_seconds: float = SUBMAP_SECONDS) -> DriftReport:
    """Estimate and optionally apply a per-submap 4-DoF correction.

    With `apply=False` the estimate is still computed and reported, which is what makes the
    on/off ablation a like-for-like comparison rather than two different pipelines.
    """
    if not ir.frames:
        return DriftReport("none: no frames", 0, 0, False)

    t = np.array([f.timestamp for f in ir.frames])
    pos = np.array([f.position for f in ir.frames])
    submap = _submap_of(t, submap_seconds)
    n_sub = int(submap.max()) + 1

    method = (f"{n_sub} submaps of {submap_seconds:.0f} s, revisit-based loop closures, "
              f"4-DoF pose graph (x, z, yaw) solved by damped least squares; "
              f"roll and pitch left to the IMU")

    if n_sub < 2:
        return DriftReport(method, n_sub, 0, False,
                           notes=["capture too short to drift measurably"])

    loops = find_loop_closures(pos, t, submap)
    if not loops:
        return DriftReport(
            method, n_sub, 0, False,
            notes=["the walk never revisits anywhere, so there is no loop to close and "
                   "accumulated drift cannot be observed, let alone removed"])

    centres = np.array([pos[submap == s][:, [0, 2]].mean(axis=0) if (submap == s).any()
                        else [0.0, 0.0] for s in range(n_sub)])

    def residuals(p):
        dx, dz, dyaw = p[:n_sub], p[n_sub:2 * n_sub], p[2 * n_sub:]
        out = []
        # Each submap should stay near where ARKit put it.
        out.append(ODOMETRY_WEIGHT * dx)
        out.append(ODOMETRY_WEIGHT * dz)
        out.append(ODOMETRY_WEIGHT * 5.0 * dyaw)
        # Consecutive submaps should not jump relative to one another.
        out.append(ODOMETRY_WEIGHT * np.diff(dx))
        out.append(ODOMETRY_WEIGHT * np.diff(dz))
        out.append(ODOMETRY_WEIGHT * 5.0 * np.diff(dyaw))
        # A revisit should land in the same place after correction.
        for a, b, offset in loops:
            ca, cb = centres[a], centres[b]
            ra = np.array([ca[0] + dx[a], ca[1] + dz[a]])
            rb = np.array([cb[0] + dx[b], cb[1] + dz[b]])
            out.append((rb - ra) - offset)
        return np.concatenate([np.atleast_1d(o).ravel() for o in out])

    sol = least_squares(residuals, np.zeros(3 * n_sub), method="lm", max_nfev=400)
    dx, dz, dyaw = sol.x[:n_sub], sol.x[n_sub:2 * n_sub], sol.x[2 * n_sub:]
    shifts = np.hypot(dx, dz)

    report = DriftReport(method, n_sub, len(loops), apply,
                         max_shift_m=float(shifts.max()), mean_shift_m=float(shifts.mean()))

    if apply:
        for i, f in enumerate(ir.frames):
            s = submap[i]
            c, sn = math.cos(dyaw[s]), math.sin(dyaw[s])
            p = f.position
            x = c * p[0] - sn * p[2] + dx[s]
            z = sn * p[0] + c * p[2] + dz[s]
            T = f.world_from_cam.copy()
            T[:3, 3] = [x, p[1], z]
            R = np.array([[c, 0, -sn], [0, 1, 0], [sn, 0, c]])
            T[:3, :3] = R @ T[:3, :3]
            f.world_from_cam = T
    else:
        report.notes.append("estimated but not applied (ablation)")
    return report
