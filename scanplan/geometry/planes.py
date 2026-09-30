"""Floor and ceiling from the gravity-aligned cloud.

The odometry origin is the camera's starting pose, not the floor, so both surfaces have to be
found from the data. Because the cloud is already gravity-aligned, they are the two dominant
peaks of a histogram of height, which is far more robust than plane RANSAC: a floor is the
only surface in a home with thousands of points at one exact height across the whole footprint.

G-CEIL wants ceiling height within 1.5 cm, so the bin width is 1 cm and the peak is refined
to the centroid of its neighbourhood rather than taken as the bin centre.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BIN_M = 0.01
REFINE_HALF_WIDTH_M = 0.03      # points within +-3 cm of the peak define the surface
MIN_SUPPORT_FRACTION = 0.005    # a real floor or ceiling holds at least 0.5% of all points

# Device depth carries a systematic offset that averaging cannot remove: published work on
# iPad Pro LiDAR puts it near 12 mm against laser truth. Until we measure it ourselves on
# ARKitScenes (bench/arkitscenes_planes.py) every surface height carries this as an
# irreducible allowance. Without it the standard error of 250,000 points is 0.1 mm, which
# would be confident garbage of exactly the kind the brief penalises.
UNMEASURED_DEPTH_BIAS_M = 0.012


@dataclass
class Level:
    height_m: float
    support: int
    rms_m: float

    @property
    def sigma_m(self) -> float:
        """One sigma on the surface height: the statistical error of the fit, plus the
        systematic depth offset we have not yet calibrated out."""
        statistical = self.rms_m / max(np.sqrt(self.support), 1.0)
        return float(np.hypot(statistical, UNMEASURED_DEPTH_BIAS_M))


def _peak(heights: np.ndarray, candidates: np.ndarray) -> Level | None:
    """Strongest 1 cm bin among `candidates`, refined to the centroid of its neighbourhood."""
    if len(candidates) == 0:
        return None
    lo, hi = candidates.min(), candidates.max()
    if hi - lo < BIN_M:
        return None
    counts, edges = np.histogram(candidates, bins=max(int((hi - lo) / BIN_M), 1))
    if counts.max() < MIN_SUPPORT_FRACTION * len(heights):
        return None

    centre = (edges[counts.argmax()] + edges[counts.argmax() + 1]) / 2
    near = candidates[np.abs(candidates - centre) < REFINE_HALF_WIDTH_M]
    if len(near) == 0:
        return None
    return Level(float(near.mean()), int(len(near)), float(near.std()))


def floor_and_ceiling(points: np.ndarray, camera_heights: np.ndarray) -> tuple[Level | None, Level | None]:
    """The floor is the strongest level below the camera, the ceiling the strongest above.

    Splitting at the camera path rather than at the global median is what makes this work on
    a capture that saw mostly floor (or mostly ceiling): the phone is always between the two.
    """
    if len(points) == 0:
        return None, None
    h = points[:, 1]
    cam = float(np.median(camera_heights))
    return _peak(h, h[h < cam - 0.10]), _peak(h, h[h > cam + 0.10])


def ceiling_height(floor: Level | None, ceiling: Level | None) -> tuple[float, float] | None:
    """Storey height and its one-sigma, or None when a surface was never seen."""
    if floor is None or ceiling is None:
        return None
    return (ceiling.height_m - floor.height_m,
            float(np.hypot(floor.sigma_m, ceiling.sigma_m)))
