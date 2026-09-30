"""Make a measured outline look like, and measure like, a floor plan.

A polygon traced from measured floor coverage is organic: every wall wanders by a few
centimetres because that is genuinely where the points fell. It is an honest boundary and a
useless drawing -- a 5 m wall arrives as fourteen segments averaging 0.4 m, none of which is
a wall length anybody can check with a tape.

Two steps fix it, in this order:

1. **Yaw alignment.** The cloud is already gravity-aligned, but not rotated about the vertical:
   the building sits at whatever angle the capture started at. Rotating so the dominant wall
   direction runs along the grid axis makes every subsequent operation cheaper and sharper.

2. **Snapping, but only where the evidence allows it.** Each edge is tested against the
   dominant directions and moved only when the move is small compared with the measurement
   noise. A wall that is genuinely at 37 degrees stays at 37 degrees. This is the difference
   between a plan that is regular because the building is, and one that is regular because
   the code insisted -- the second kind is confidently wrong, which the brief penalises
   harder than being visibly rough.
"""
from __future__ import annotations

import math

import numpy as np

SNAP_TOLERANCE_M = 0.08     # how far a vertex may move to straighten a wall
MIN_WALL_M = 0.25           # shorter than this is a corner artefact, not a wall


def dominant_yaw(points_xz: np.ndarray, *, bins: int = 180) -> float:
    """The building's main horizontal direction, in radians, modulo 90 degrees.

    Taken from the distribution of local edge directions in the top-down point scatter: the
    walls dominate it because walls are where points line up.
    """
    if len(points_xz) < 100:
        return 0.0
    sample = points_xz[np.random.default_rng(0).choice(len(points_xz),
                                                       size=min(len(points_xz), 40000),
                                                       replace=False)]
    centred = sample - sample.mean(axis=0)
    # Principal direction of the second-moment matrix, then reduced modulo 90 degrees.
    cov = centred.T @ centred
    vals, vecs = np.linalg.eigh(cov)
    v = vecs[:, int(np.argmax(vals))]
    return float(math.atan2(v[1], v[0]) % (math.pi / 2))


def rotate_about_y(points: np.ndarray, yaw: float) -> np.ndarray:
    """Rotate an (n, 3) cloud about the vertical axis. Gravity alignment is preserved."""
    c, s = math.cos(-yaw), math.sin(-yaw)
    out = points.copy()
    out[:, 0] = points[:, 0] * c - points[:, 2] * s
    out[:, 2] = points[:, 0] * s + points[:, 2] * c
    return out


def rotate_xz(xz: np.ndarray, yaw: float) -> np.ndarray:
    c, s = math.cos(yaw), math.sin(yaw)
    xz = np.atleast_2d(xz)
    return np.stack([xz[:, 0] * c - xz[:, 1] * s, xz[:, 0] * s + xz[:, 1] * c], axis=-1)


def _drop_short_edges(poly: np.ndarray, min_len: float) -> np.ndarray:
    """Collapse edges too short to be walls, merging their endpoints."""
    pts = [poly[0]]
    for p in poly[1:]:
        if math.dist(p, pts[-1]) >= min_len:
            pts.append(p)
    while len(pts) > 3 and math.dist(pts[0], pts[-1]) < min_len:
        pts.pop()
    return np.asarray(pts)


def rectify(poly: np.ndarray, *, tolerance_m: float = SNAP_TOLERANCE_M,
            min_wall_m: float = MIN_WALL_M) -> np.ndarray:
    """Straighten a polygon onto the grid axes where the evidence permits.

    Assumes the caller has already yaw-aligned, so the dominant directions are 0 and 90
    degrees. An edge is made axis-parallel only when doing so moves both endpoints less than
    `tolerance_m`; otherwise it is left exactly as measured.
    """
    poly = _drop_short_edges(np.asarray(poly, float), min_wall_m)
    if len(poly) < 3:
        return poly

    out = poly.copy()
    n = len(out)
    for i in range(n):
        a, b = out[i], out[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            continue
        if abs(dy) <= abs(dx):                       # nearly horizontal
            if abs(dy) / 2 <= tolerance_m:
                mid = (a[1] + b[1]) / 2
                out[i][1] = out[(i + 1) % n][1] = mid
        else:                                        # nearly vertical
            if abs(dx) / 2 <= tolerance_m:
                mid = (a[0] + b[0]) / 2
                out[i][0] = out[(i + 1) % n][0] = mid

    return _drop_short_edges(out, min_wall_m)


def polygon_area(poly: np.ndarray) -> float:
    n = len(poly)
    return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1]
                   for i in range(n))) / 2
