"""Put two independent walks of one property into one coordinate frame.

Two walks of the same flat come out of the pipeline in two different frames: each is yaw-aligned
to its *own* dominant wall direction (a quantity defined only modulo 90 degrees, so the two
walks can differ by any multiple of a right angle plus a residual) and each starts at its own
origin. Nothing downstream can compare them room by room until that is fixed.

This module fixes it the only way the data allows: by searching for the rigid 2D transform that
makes the two walks' *measured floor coverage* coincide. No orientation prior, no landmark,
nothing from any reference. The search is exhaustive over the full circle, which matters
because a 90-degree ambiguity cannot be resolved by a local method -- descent from the identity
would happily settle into a quarter-turn error that looks locally fine.

## Objective, and why coverage first and walls second

Stage 1 maximises the intersection-over-union of the two floor-coverage masks, swept over every
yaw in the range at the stated step. Coverage is the right coarse objective because it is dense
and because it is the one quantity the two walks already agree on (total footprints 3.2%
apart), so the IoU surface has one clear basin per quarter-turn.

Stage 2 refines yaw and shift against the two *wall* masks, in a window around stage 1. Walls
are what a floor plan is made of and they are far sharper than a coverage boundary -- a wall is
two or three cells wide, a coverage boundary wanders by 10 cm -- but they are also holed
wherever the phone never pointed, which is why they are not trusted to find the basin, only to
sharpen inside it.

Both stages evaluate translation by FFT cross-correlation, which scores *every* integer cell
offset at once instead of hill-climbing to a local optimum.

## Masks are warped, not splatted

Every rotation here is an image warp (`cv2.warpAffine`, nearest neighbour), never a rotation of
the occupied cell centres followed by re-binning. Re-binning is the obvious implementation and
it is quietly wrong for a *search*: a filled region rotated by 0 degrees re-bins onto every
cell, the same region rotated by 45 degrees leaves holes, so the score is a function of how
diagonal the yaw is as well as of how well the shapes agree. On this pair that bias points at
multiples of 90 degrees -- which is near the right answer, so it would have improved the score
while corrupting the angle.

## What this buys, and what it does not

It buys a frame, and so a correspondence *candidate*: rooms can be paired by where they are
rather than by how big they are. It does not buy agreement. If two walks genuinely cut the
floor into different rooms, registration exposes that as a one-to-many overlap instead of
hiding it -- see `bench/same_flat_register.py`, which publishes the whole overlap matrix and
not only the pairs that came out clean.

Registration precision also does not enter the dimension comparison that benchmark reports:
room dimensions there are the sides of each room's minimum-area rectangle, measured in each
walk's own frame, and those are invariant under rigid motion. The fit is used for pairing only.
That split is deliberate -- it means a 0.3 degree yaw error can neither manufacture nor destroy
a dimension pass.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.signal import fftconvolve

COARSE_CELL_M = 0.04        # coverage sweep: half the raster resolution, 4x fewer FFT samples.
                            # The refinement stages run at whatever cell the grids carry, so
                            # this value never reaches the returned transform.
WALL_TOLERANCE_M = 0.04     # the target wall mask is dilated by this before correlating, so a
                            # wall 4 cm thicker in one walk still scores as a hit
PAD_CELLS = 3


@dataclass
class Fit:
    """A rigid 2D transform taking the source walk into the target walk's frame."""

    yaw_rad: float
    shift_m: np.ndarray            # applied after the rotation, in metres (x, z)
    coverage_iou: float = 0.0      # IoU of the two coverage masks once registered
    wall_overlap_frac: float = 0.0  # share of source wall cells on a target wall cell
    wall_residual_m: float = float("inf")   # median source-wall to nearest-target-wall distance

    @property
    def yaw_deg(self) -> float:
        return math.degrees(self.yaw_rad)

    def matrix(self) -> np.ndarray:
        c, s = math.cos(self.yaw_rad), math.sin(self.yaw_rad)
        return np.array([[c, -s], [s, c]])

    def apply(self, xz) -> np.ndarray:
        xz = np.atleast_2d(np.asarray(xz, float))
        return xz @ self.matrix().T + self.shift_m

    def as_dict(self) -> dict:
        return {
            "yaw_deg": round(self.yaw_deg, 3),
            "shift_m": [round(float(self.shift_m[0]), 3), round(float(self.shift_m[1]), 3)],
            "coverage_iou": round(self.coverage_iou, 4),
            "wall_overlap_fraction": round(self.wall_overlap_frac, 3),
            "wall_residual_median_cm": round(100 * self.wall_residual_m, 2),
        }


# --- raster plumbing ----------------------------------------------------------------

def _downsample(mask: np.ndarray, factor: int) -> np.ndarray:
    """Coarsen a binary mask, keeping any cell that was partly occupied."""
    if factor == 1:
        return mask.astype(np.float32)
    h, w = mask.shape
    pad = ((0, -h % factor), (0, -w % factor))
    m = np.pad(mask.astype(np.float32), pad)
    return (m.reshape(m.shape[0] // factor, factor, m.shape[1] // factor, factor)
             .max(axis=(1, 3)))


def _warp(mask: np.ndarray, origin: np.ndarray, cell: float, R: np.ndarray,
          t: np.ndarray, *, out_origin=None, out_shape=None):
    """Apply `x -> R x + t` to a mask in world coordinates, returning (image, origin).

    A pixel centre of the source sits at world `origin + (p + 0.5) * cell`, so the affine
    taking source pixels to destination pixels is `R p + b` with
    `b = (R (origin + 0.5 cell) + t - out_origin) / cell - 0.5`.
    """
    h, w = mask.shape
    corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], float) * cell + origin
    moved = corners @ R.T + t
    if out_origin is None:
        out_origin = moved.min(axis=0) - PAD_CELLS * cell
    if out_shape is None:
        span = np.ceil((moved.max(axis=0) + PAD_CELLS * cell - out_origin) / cell).astype(int)
        out_shape = (int(span[1]) + 1, int(span[0]) + 1)
    b = (R @ (origin + 0.5 * cell) + t - out_origin) / cell - 0.5
    M = np.hstack([R, b.reshape(2, 1)]).astype(np.float64)
    warped = cv2.warpAffine(mask.astype(np.uint8), M, (out_shape[1], out_shape[0]),
                            flags=cv2.INTER_NEAREST, borderValue=0)
    return warped, np.asarray(out_origin, float)


def _best_shift(target: np.ndarray, source: np.ndarray):
    """Cell offset of `source` maximising overlap with `target`, and that overlap count.

    `fftconvolve(a, b[::-1, ::-1], 'full')[i, j] == sum_pq a[p, q] b[p + dr, q + dc]` with
    `dr = hb - 1 - i`, `dc = wb - 1 - j`, so the offset to apply to `source` is `(-dr, -dc)`.
    Every integer offset is scored, so this is a global optimum over translation.
    """
    corr = fftconvolve(target.astype(np.float32), source.astype(np.float32)[::-1, ::-1],
                       mode="full")
    i, j = np.unravel_index(int(np.argmax(corr)), corr.shape)
    return (int(i) - source.shape[0] + 1, int(j) - source.shape[1] + 1), float(corr[i, j])


def _sweep(source: np.ndarray, src_origin: np.ndarray, target: np.ndarray,
           tgt_origin: np.ndarray, cell: float, yaws, *, iou: bool):
    """Best (score, yaw, shift) over `yaws`; rotation is taken about the source centroid."""
    rows, cols = np.nonzero(source)
    centre = np.array([cols.mean() + 0.5, rows.mean() + 0.5]) * cell + src_origin
    target_n = float(target.sum())
    best = None
    for yaw in np.atleast_1d(yaws):
        c, s = math.cos(yaw), math.sin(yaw)
        R = np.array([[c, -s], [s, c]])
        t = centre - R @ centre
        rot, rot_origin = _warp(source, src_origin, cell, R, t)
        (dr, dc), inter = _best_shift(target, rot)
        score = (inter / (target_n + float(rot.sum()) - inter) if iou
                 else inter / max(float(rot.sum()), 1.0))
        if best is None or score > best[0]:
            delta = np.array([tgt_origin[0] - rot_origin[0] + dc * cell,
                              tgt_origin[1] - rot_origin[1] + dr * cell])
            best = (score, float(yaw), t + delta)
    return best


# --- public API ---------------------------------------------------------------------

def warp_mask_to(source_grid, mask: np.ndarray, fit: Fit, target_grid) -> np.ndarray:
    """A source-frame mask resampled onto the target grid under `fit`."""
    warped, _ = _warp(mask, source_grid.origin, source_grid.cell_m, fit.matrix(), fit.shift_m,
                      out_origin=target_grid.origin, out_shape=target_grid.shape)
    return warped.astype(bool)


def _coverage_iou(target, source, fit: Fit) -> float:
    t = target["coverage"].astype(bool)
    s = warp_mask_to(source["grid"], source["coverage"].astype(np.uint8), fit, target["grid"])
    # Source area pushed outside the target grid is union-only; count it so a fit that slides
    # the walk off the edge cannot score well.
    full, _ = _warp(source["coverage"].astype(np.uint8), source["grid"].origin,
                    source["grid"].cell_m, fit.matrix(), fit.shift_m)
    outside = max(int(full.sum()) - int(s.sum()), 0)
    union = int((t | s).sum()) + outside
    return float((t & s).sum()) / max(union, 1)


def _wall_agreement(target, source, fit: Fit):
    """Share of registered source wall cells on a target wall cell, and median miss distance."""
    tgt = target["wall_mask"].astype(np.uint8)
    dist = cv2.distanceTransform((1 - tgt), cv2.DIST_L2, 5) * target["grid"].cell_m
    src = warp_mask_to(source["grid"], source["wall_mask"].astype(np.uint8), fit,
                       target["grid"])
    if not src.any():
        return 0.0, float("inf")
    d = dist[src]
    return float((d <= target["grid"].cell_m).mean()), float(np.median(d))


def register(target: dict, source: dict, *, yaw_step_deg: float = 1.0,
             refine_window_deg: float = 2.0, refine_step_deg: float = 0.1,
             refine_on_walls: bool = True) -> Fit:
    """Rigid transform placing `source` into `target`'s frame.

    `target` and `source` are the artifact dicts filled by
    `scanplan.pipeline.run(..., artifacts=d)`: each must carry `grid`, `coverage`, `wall_mask`.

    Stage 1 sweeps the full circle on coverage IoU at `yaw_step_deg`, on a coarsened raster.
    Stage 2 (optional) re-sweeps +-`refine_window_deg` at `refine_step_deg` on the wall masks
    at full resolution. The returned Fit always carries both the coverage IoU and the wall
    residual at whichever solution was chosen, so the two can be read against each other.
    """
    f = max(1, int(round(COARSE_CELL_M / target["grid"].cell_m)))
    cell_c = target["grid"].cell_m * f
    tgt_c = _downsample(target["coverage"].astype(bool), f)
    src_c = _downsample(source["coverage"].astype(bool), f)
    yaws = np.deg2rad(np.arange(-180.0, 180.0, yaw_step_deg))
    _, yaw, _ = _sweep(src_c, source["grid"].origin, tgt_c, target["grid"].origin,
                       cell_c, yaws, iou=True)

    # Re-seat at the pipeline's own resolution so the 4 cm sweep cell never reaches the result.
    fine = np.deg2rad(np.arange(-yaw_step_deg, yaw_step_deg + 1e-9, yaw_step_deg / 4)) + yaw
    _, yaw, shift = _sweep(source["coverage"].astype(bool), source["grid"].origin,
                           target["coverage"].astype(bool), target["grid"].origin,
                           target["grid"].cell_m, fine, iou=True)

    if refine_on_walls:
        k = int(WALL_TOLERANCE_M / target["grid"].cell_m) | 1
        tgt_w = cv2.dilate(target["wall_mask"].astype(np.uint8), np.ones((k, k), np.uint8))
        window = np.deg2rad(np.arange(-refine_window_deg, refine_window_deg + 1e-9,
                                      refine_step_deg)) + yaw
        _, yaw, shift = _sweep(source["wall_mask"].astype(bool), source["grid"].origin,
                               tgt_w, target["grid"].origin, target["grid"].cell_m,
                               window, iou=False)

    fit = Fit(yaw_rad=yaw, shift_m=shift)
    fit.coverage_iou = _coverage_iou(target, source, fit)
    fit.wall_overlap_frac, fit.wall_residual_m = _wall_agreement(target, source, fit)
    return fit
