"""Point cloud -> wall map, in the horizontal plane.

The cloud is already gravity-aligned, so a wall is simply a place where many points stack up
over a range of heights. Projecting a height band down onto a 2 cm grid turns wall-finding
into an image problem, which is both far faster and far more robust than fitting planes in
3D: a 3 m wall seen edge-on has few points but a very sharp footprint.

Band choice matters. Below ~0.4 m is furniture bases and clutter; above ~1.9 m is ceiling
fixtures, curtain rails and the tops of cupboards. Between those, almost everything that is
tall and thin is a wall.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

CELL_M = 0.02               # 2 cm, matching the fusion voxel
BAND_LOW_M = 0.40           # above the floor
BAND_HIGH_M = 1.90
MARGIN_M = 0.50             # padding around the occupied extent


@dataclass
class Grid:
    """A top-down raster and the transform back to metres."""

    data: np.ndarray            # (h, w) float
    origin: np.ndarray          # world (x, z) of pixel (0, 0)
    cell_m: float = CELL_M

    def to_world(self, cols, rows) -> np.ndarray:
        """Pixel centres -> world (x, z)."""
        return np.stack([self.origin[0] + (np.asarray(cols) + 0.5) * self.cell_m,
                         self.origin[1] + (np.asarray(rows) + 0.5) * self.cell_m], axis=-1)

    def to_pixel(self, xz) -> np.ndarray:
        return np.floor((np.asarray(xz) - self.origin) / self.cell_m).astype(int)

    @property
    def shape(self):
        return self.data.shape


def density(points: np.ndarray, floor_y: float, *, cell_m: float = CELL_M,
            band=(BAND_LOW_M, BAND_HIGH_M)) -> Grid:
    """Count points per cell over the wall height band."""
    h = points[:, 1] - floor_y
    band_pts = points[(h > band[0]) & (h < band[1])]
    if len(band_pts) == 0:
        raise ValueError("no points in the wall height band; is the floor level right?")

    xz = band_pts[:, [0, 2]]
    lo = xz.min(axis=0) - MARGIN_M
    hi = xz.max(axis=0) + MARGIN_M
    size = np.ceil((hi - lo) / cell_m).astype(int) + 1

    idx = np.floor((xz - lo) / cell_m).astype(int)
    flat = np.bincount(idx[:, 1] * size[0] + idx[:, 0], minlength=size[0] * size[1])
    return Grid(flat.reshape(size[1], size[0]).astype(np.float32), lo, cell_m)


def wall_mask(grid: Grid, *, percentile: float = 92.0, min_count: int = 3) -> np.ndarray:
    """Cells dense enough to be structure rather than a passing point.

    The threshold is taken from the distribution of *occupied* cells only. An absolute count
    would depend on how long the phone lingered, which varies hugely within one walk.
    """
    occupied = grid.data[grid.data > 0]
    thr = max(np.percentile(occupied, percentile), min_count)
    mask = (grid.data >= thr).astype(np.uint8)
    # Close single-cell gaps where a doorway reveal or a mirror dropped the count.
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))


def dominant_orientations(mask: np.ndarray, *, top: int = 2) -> list[float]:
    """The building's main wall directions, in radians.

    Angles are clustered modulo 90 degrees, so a Manhattan building collapses to one number.
    This is a measurement, not an assumption: a 45-degree or curved building simply reports
    a different set, and nothing downstream is forced to snap to it.
    """
    lines = cv2.HoughLinesP(mask * 255, 1, np.pi / 360, threshold=30,
                            minLineLength=int(0.6 / CELL_M), maxLineGap=int(0.1 / CELL_M))
    if lines is None:
        return []
    angles, weights = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        angles.append(np.arctan2(y2 - y1, x2 - x1) % (np.pi / 2))
        weights.append(np.hypot(x2 - x1, y2 - y1))

    hist, edges = np.histogram(angles, bins=90, range=(0, np.pi / 2), weights=weights)
    order = np.argsort(hist)[::-1]
    out = []
    for b in order:
        if hist[b] <= 0:
            break
        centre = (edges[b] + edges[b + 1]) / 2
        if all(abs(centre - o) > np.deg2rad(8) for o in out):
            out.append(float(centre))
        if len(out) >= top:
            break
    return out


SENSOR_RANGE_M = 4.0        # useful iPhone LiDAR reach; beyond this nothing was measured
FLOOR_BAND_M = 0.06         # points this close to the floor plane are floor


def floor_coverage(points: np.ndarray, floor_y: float, grid: Grid,
                   *, band_m: float = FLOOR_BAND_M) -> np.ndarray:
    """Cells where floor was actually measured.

    This is the honest definition of floor area, and it is why the plan does not rely on a
    flood fill. A fill answers "could I walk here without crossing a wall I happened to
    detect", which silently claims the outdoors whenever a wall went unobserved. This answers
    "did the sensor see floor here", which cannot invent area that was never measured.

    Furniture leaves holes, so small ones are closed and fully-enclosed ones filled: the floor
    under a bed is floor, even though no ray ever reached it.
    """
    h = points[:, 1] - floor_y
    floor_pts = points[np.abs(h) < band_m]
    cov = np.zeros(grid.shape, np.uint8)
    if len(floor_pts) == 0:
        return cov

    px = grid.to_pixel(floor_pts[:, [0, 2]])
    ok = ((px[:, 1] >= 0) & (px[:, 1] < grid.shape[0]) &
          (px[:, 0] >= 0) & (px[:, 0] < grid.shape[1]))
    cov[px[ok, 1], px[ok, 0]] = 1

    # Close gaps up to ~20 cm (chair legs, cable runs, sparse returns).
    k = int(0.20 / grid.cell_m) | 1
    cov = cv2.morphologyEx(cov, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))

    # Fill enclosed holes: flood the exterior from a padded border, then invert.
    padded = cv2.copyMakeBorder(cov, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = padded.copy()
    cv2.floodFill(ff, np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8), (0, 0), 1)
    holes = (1 - ff)[1:-1, 1:-1]
    return (cov | holes).astype(np.uint8)


def observed(grid: Grid, trajectory_xz: np.ndarray, *, reach_m: float = SENSOR_RANGE_M) -> np.ndarray:
    """Cells the sensor could plausibly have seen: within `reach_m` of the camera path.

    This exists because a flood fill alone is not safe. The wall mask always has holes --
    stretches the phone never pointed at, glass, a doorway left open to a stairwell -- and a
    fill escaping through one of them will happily claim the whole outdoors as floor. Bounding
    by sensor reach means the plan only ever asserts floor that was actually measured, which
    is the honest failure direction: too little, never invented.
    """
    seeds = np.zeros(grid.shape, np.uint8)
    px = grid.to_pixel(trajectory_xz)
    ok = ((px[:, 1] >= 0) & (px[:, 1] < grid.shape[0]) &
          (px[:, 0] >= 0) & (px[:, 0] < grid.shape[1]))
    seeds[px[ok, 1], px[ok, 0]] = 1
    # Distance (in cells) from the nearest camera position.
    dist = cv2.distanceTransform((1 - seeds).astype(np.uint8), cv2.DIST_L2, 5)
    return (dist <= reach_m / grid.cell_m).astype(np.uint8)


def free_space(grid: Grid, mask: np.ndarray, trajectory_xz: np.ndarray,
               *, reach_m: float = SENSOR_RANGE_M) -> np.ndarray:
    """Interior floor: flood-filled from the camera path, clipped to what was observed.

    The trajectory is the one set of points guaranteed to be inside the property and never
    inside a wall, so it seeds the fill without any need to guess.
    """
    ff = np.where(mask.astype(bool), 0, 255).astype(np.uint8)
    flood_mask = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), np.uint8)

    seeded = 0
    for x, z in trajectory_xz:
        c, r = grid.to_pixel((x, z))
        if 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and ff[r, c] == 255:
            cv2.floodFill(ff, flood_mask, (int(c), int(r)), 128)
            seeded += 1
    if seeded == 0:
        raise ValueError("no camera position landed on free space; the wall mask may be too thick")

    free = (ff == 128).astype(np.uint8) & observed(grid, trajectory_xz, reach_m=reach_m)
    # Drop specks left by the clipping boundary.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    keep = np.zeros(free.shape, np.uint8)
    min_cells = int(0.5 / grid.cell_m ** 2)     # ignore anything under 0.5 m2
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_cells:
            keep[labels == i] = 1
    return keep
