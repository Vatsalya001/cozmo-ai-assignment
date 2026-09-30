"""Floor coverage -> rooms, polygons and the openings between them.

Rooms are separated by cutting the floor at doorways rather than by clustering points. A
doorway is a narrow neck in an otherwise wide floor region, so an erosion that is wider than
a door but narrower than a room splits the floor into room cores; growing those cores back
under a watershed recovers the full extent and puts the boundary exactly at the neck.

That ordering matters: it means an open-plan kitchen stays one room, because nothing narrow
separates it, while a real doorway splits reliably even when the wall either side went
unobserved.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .walls import Grid

DOOR_MAX_M = 1.30           # anything narrower than this may be a doorway
ROOM_MIN_AREA_M2 = 1.20     # smaller than a shower tray: not a room
SIMPLIFY_M = 0.15          # polygon simplification tolerance: below a wall thickness


@dataclass
class Opening:
    """A neck between two rooms: a doorway, or an open connection."""

    id: str
    centre_xz: np.ndarray
    width_m: float
    rooms: tuple[int, int]


@dataclass
class Room:
    id: int
    polygon_xz: np.ndarray          # (n, 2) metres, closed implicitly
    area_m2: float
    mask: np.ndarray = field(repr=False, default=None)

    @property
    def perimeter_m(self) -> float:
        p = self.polygon_xz
        return float(sum(math.dist(p[i], p[(i + 1) % len(p)]) for i in range(len(p))))

    def wall_lengths(self) -> list[float]:
        p = self.polygon_xz
        return [float(math.dist(p[i], p[(i + 1) % len(p)])) for i in range(len(p))]


def split_rooms(free: np.ndarray, grid: Grid, *, door_max_m: float = DOOR_MAX_M,
                min_area_m2: float = ROOM_MIN_AREA_M2) -> np.ndarray:
    """Label the floor into rooms, cutting at doorway-width necks.

    Returns an int32 label image, 0 = not floor.
    """
    cell = grid.cell_m
    # Erode by half a door width: necks vanish, room interiors survive.
    r = max(int((door_max_m / 2) / cell), 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    cores = cv2.erode(free, kernel)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(cores, connectivity=4)
    min_cells = int(min_area_m2 / cell ** 2)
    keep, next_id = np.zeros_like(labels), 1
    for i in range(1, n):
        # Compare against the eroded area, which is much smaller than the room itself.
        if stats[i, cv2.CC_STAT_AREA] >= max(min_cells // 4, 16):
            keep[labels == i] = next_id
            next_id += 1

    if next_id == 1:                      # erosion removed everything: one room
        n2, l2, stats2, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
        out = np.zeros_like(l2)
        k = 1
        for i in range(1, n2):
            if stats2[i, cv2.CC_STAT_AREA] >= min_cells:
                out[l2 == i] = k
                k += 1
        return out.astype(np.int32)

    # Grow the cores back over the full floor. Watershed needs a 3-channel image; the
    # distance to the nearest wall makes the ridges fall at the necks.
    dist = cv2.distanceTransform(free, cv2.DIST_L2, 5)
    relief = cv2.cvtColor(cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
                          cv2.COLOR_GRAY2BGR)
    markers = keep.astype(np.int32).copy()
    markers[free == 0] = -1               # everything off-floor is known background
    cv2.watershed(relief, markers)

    markers[markers < 0] = 0
    markers[free == 0] = 0

    # Drop rooms that ended up too small once grown.
    out = np.zeros_like(markers)
    k = 1
    for lbl in range(1, markers.max() + 1):
        if (markers == lbl).sum() * cell ** 2 >= min_area_m2:
            out[markers == lbl] = k
            k += 1
    return out.astype(np.int32)


def polygons(labels: np.ndarray, grid: Grid, *, simplify_m: float = SIMPLIFY_M) -> list[Room]:
    """One simplified polygon per room, in metres.

    The raw coverage boundary is ragged -- it is the edge of a scatter of measured floor
    points, not a drawn line -- so it is smoothed before tracing. Without this a 3 by 4 m
    room traces as 180 corners with an 80 m perimeter, which is arithmetically true of the
    pixel boundary and useless as a wall length.
    """
    cell = grid.cell_m
    smooth_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.12 / cell) | 1,) * 2)
    rooms = []
    for lbl in range(1, labels.max() + 1):
        mask = (labels == lbl).astype(np.uint8)
        area = float(mask.sum() * cell ** 2)          # area from the unsmoothed mask
        smoothed = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, smooth_k),
                                    cv2.MORPH_OPEN, smooth_k)
        contours, _ = cv2.findContours(smoothed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        approx = cv2.approxPolyDP(c, simplify_m / cell, True).reshape(-1, 2)
        if len(approx) < 3:
            continue
        rooms.append(Room(id=lbl, polygon_xz=grid.to_world(approx[:, 0], approx[:, 1]),
                          area_m2=area, mask=mask))
    return rooms


def openings(labels: np.ndarray, grid: Grid, free: np.ndarray,
             *, door_max_m: float = DOOR_MAX_M) -> list[Opening]:
    """Where two rooms touch, and how wide the gap is.

    Width is twice the distance from the contact point to the nearest non-floor cell, which is
    the clear opening rather than the frame-to-frame span. The distance must be measured on
    the *unsplit* floor (`free`), not on the labels: the split leaves a ridge of zeros exactly
    at the doorway, so measuring there returns one pixel for every opening in the building.
    """
    cell = grid.cell_m
    dist = cv2.distanceTransform(free.astype(np.uint8), cv2.DIST_L2, 5)
    found: dict[tuple[int, int], list] = {}

    # Watershed leaves a one-pixel ridge between rooms, so labels never touch directly.
    # Each is dilated slightly to find where they meet across it.
    grown = {}
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for lbl in range(1, int(labels.max()) + 1):
        grown[lbl] = cv2.dilate((labels == lbl).astype(np.uint8), k3)

    ids = sorted(grown)
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1:]:
            overlap = grown[a_id] & grown[b_id]
            if not overlap.any():
                continue
            for r, c in zip(*np.nonzero(overlap)):
                found.setdefault((a_id, b_id), []).append((r, c, float(dist[r, c])))

    out = []
    for i, (key, cells) in enumerate(sorted(found.items()), 1):
        rows = np.array([c[0] for c in cells])
        cols = np.array([c[1] for c in cells])
        width = 2.0 * float(np.median([c[2] for c in cells])) * cell
        if width > door_max_m * 2.5:        # a whole open side, not an opening
            continue
        centre = grid.to_world(cols.mean(), rows.mean())
        out.append(Opening(id=f"O{i}", centre_xz=np.asarray(centre), width_m=width, rooms=key))
    return out
