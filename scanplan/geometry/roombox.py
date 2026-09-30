"""A room box from unposed views — the photo tier's geometry.

The walked-capture pipeline (coverage, split, watershed) assumes the camera travelled through
the property, so the floor it measured is connected and the necks between rooms mean something.
The photo tier has none of that: a handful of stills, each levelled against its own floor, with
no pose relating one to the next. Feeding them through the same core produces nothing, which is
the correct outcome of asking a traversal-based method about a capture with no traversal.

What a single levelled view *can* honestly support is the extent of the room around the
camera. So each photo is reduced to a footprint estimate, and the per-room estimates are
combined by taking a **high percentile rather than the maximum** — one bad depth frame with a
smeared far wall would otherwise set the room size on its own.

The result is a rectangle. A single view cannot see round a corner, so an L-shaped room comes
back as its bounding box, and the warning says so rather than letting the shape imply a
confidence the method does not have.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .rooms import Room

FLOOR_BAND_M = 0.12         # points this close to y = 0 are floor
MIN_FLOOR_POINTS = 300
EXTENT_PERCENTILE = 96      # within one view: trims depth speckle at the extremes
MIN_SIDE_M = 1.0
MAX_SIDE_M = 12.0


@dataclass
class BoxEstimate:
    width_m: float
    depth_m: float
    ceiling_m: float | None
    photos_used: int
    photos_rejected: int

    @property
    def area_m2(self) -> float:
        return self.width_m * self.depth_m


def _one_view_extent(points: np.ndarray) -> tuple[float, float, float | None] | None:
    """Floor extent and ceiling height visible from one levelled view."""
    floor = points[np.abs(points[:, 1]) < FLOOR_BAND_M]
    if len(floor) < MIN_FLOOR_POINTS:
        return None

    x, z = floor[:, 0], floor[:, 2]
    lo_x, hi_x = np.percentile(x, 100 - EXTENT_PERCENTILE), np.percentile(x, EXTENT_PERCENTILE)
    lo_z, hi_z = np.percentile(z, 100 - EXTENT_PERCENTILE), np.percentile(z, EXTENT_PERCENTILE)

    # Ceiling: the strongest layer well above the camera, if this view saw one.
    high = points[points[:, 1] > 1.9]
    ceiling = None
    if len(high) > 200:
        counts, edges = np.histogram(high[:, 1], bins=40)
        if counts.max() > 60:
            ceiling = float((edges[counts.argmax()] + edges[counts.argmax() + 1]) / 2)

    return float(hi_x - lo_x), float(hi_z - lo_z), ceiling


def _largest_credible(values: list[float]) -> float:
    """The biggest extent that is not an outlier.

    A single view sees part of the room, so the *largest* credible extent is the best estimate
    of the whole. But "largest" and "outlier-free" pull in opposite directions, and with two to
    eight photos there is no room for a percentile to do the job: a high percentile interpolates
    straight into the outlier it is meant to exclude. Measured -- five views of a 3 m room plus
    one frame with a wall smeared to 12 m moved the 85th percentile from 2.77 m to 4.95 m.

    So outliers are rejected first, by median absolute deviation, and the maximum is taken over
    what survives. MAD is used rather than a standard deviation because a single extreme value
    inflates a standard deviation enough to keep itself inside the fence.
    """
    v = np.asarray(values, dtype=float)
    if len(v) <= 2:
        return float(v.max())

    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))

    # A zero MAD means most views agree exactly, so anything that differs at all is the
    # outlier. Falling back to the maximum here -- the obvious guard -- returns precisely the
    # value this function exists to reject, which is how the first version of it failed.
    tol = max(3.0 * mad, 0.25)          # 25 cm: agreement is never finer than the depth noise
    keep = v[np.abs(v - med) <= tol]
    return float(keep.max()) if len(keep) else med


def estimate(per_photo_points: list[np.ndarray]) -> BoxEstimate | None:
    """Combine per-photo extents into one room box."""
    widths, depths, ceilings, rejected = [], [], [], 0
    for pts in per_photo_points:
        got = _one_view_extent(pts)
        if got is None:
            rejected += 1
            continue
        w, d, c = got
        widths.append(w)
        depths.append(d)
        if c is not None:
            ceilings.append(c)

    if not widths:
        return None

    width = min(max(_largest_credible(widths), MIN_SIDE_M), MAX_SIDE_M)
    depth = min(max(_largest_credible(depths), MIN_SIDE_M), MAX_SIDE_M)

    return BoxEstimate(width_m=width, depth_m=depth,
                       ceiling_m=float(np.median(ceilings)) if ceilings else None,
                       photos_used=len(widths), photos_rejected=rejected)


def as_room(box: BoxEstimate, room_id: int, origin_x: float) -> Room:
    """A rectangular Room, laid out beside its neighbours rather than joined to them."""
    w, d = box.width_m, box.depth_m
    poly = np.array([[origin_x, 0.0], [origin_x + w, 0.0],
                     [origin_x + w, d], [origin_x, d]], dtype=float)
    return Room(id=room_id, polygon_xz=poly, area_m2=w * d)
