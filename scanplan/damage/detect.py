"""Damage regions from wall geometry.

A wall is flat. Where the measured surface departs from the plane fitted through it, something
is on or in that wall -- blistered plaster, a bulge, a hole, a missing patch. That is a
geometric measurement, so it comes with a metric extent for free, which is exactly what the
contract asks for: "per-surface damage regions with class and metric extent".

What geometry cannot do is *name* the defect. Telling peeling paint from a water stain from
mould is appearance, not shape, and a stain that has not lifted the plaster is perfectly flat.
So the class here is inferred from shape alone and reported with low confidence; a
vision-language model over the RGB frames is the right instrument for naming, and slots in at
`classify_appearance` without disturbing the geometry.

Reporting a shape-derived class as if it were a visual identification would be exactly the
confident garbage the brief penalises, so `class_source` travels with every region.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..ir import CaptureIR

PROTRUSION_M = 0.012        # below this is measurement noise, not damage
MAX_PROTRUSION_M = 0.06     # above this is furniture, not a defect in the wall surface
MIN_REGION_M2 = 0.03        # smaller than a postcard: not worth reporting
MAX_REGION_M2 = 1.00        # larger than this is furniture or a misfitted wall
WALL_BAND_M = 0.12          # how far from the plane a point can be and still be "on" the wall


@dataclass
class DamageRegion:
    id: str
    surface_id: str
    damage_class: str
    class_source: str                   # "shape" or "appearance"
    class_confidence: float
    width_m: float
    height_m: float
    area_m2: float
    height_above_floor_m: float
    mean_protrusion_m: float
    max_protrusion_m: float
    outline_xz: np.ndarray = field(repr=False, default=None)

    def as_dict(self) -> dict:
        from ..measure import from_sigma
        sigma = 0.02
        return {
            "id": self.id,
            "surface_id": self.surface_id,
            "class": self.damage_class,
            "width_m": from_sigma(self.width_m, sigma, method=f"bounding box on the wall plane "
                                                              f"({self.class_source})").as_dict(),
            "height_m": from_sigma(self.height_m, sigma, method="bounding box on the wall plane").as_dict(),
            "area_m2": from_sigma(self.area_m2, self.area_m2 * 0.15,
                                  method="extent of points departing from the wall plane").as_dict(),
            "height_above_floor_m": from_sigma(self.height_above_floor_m, sigma,
                                               method="lower edge above the floor plane").as_dict(),
            "confidence": round(self.class_confidence, 3),
            "views": 0,
        }


def classify_by_shape(width_m: float, height_m: float, area_m2: float,
                      max_protrusion_m: float) -> tuple[str, float]:
    """A class from shape alone, with deliberately modest confidence.

    Only two shapes are genuinely separable without appearance: something long and thin, and
    something broad. Everything else is reported as `other` rather than guessed at.
    """
    long_side, short_side = max(width_m, height_m), min(width_m, height_m)
    aspect = long_side / max(short_side, 1e-6)

    if aspect > 6.0 and short_side < 0.10:
        return "crack", 0.45
    if max_protrusion_m > 0.02 and area_m2 > 0.05:
        return "peeling_paint", 0.40
    return "other", 0.25


def _wall_planes(ir: CaptureIR, rooms, floor_y: float) -> list[tuple[str, np.ndarray, float]]:
    """(surface_id, unit normal in xz, offset) for every wall segment of every room."""
    out = []
    for room in rooms:
        poly = room.polygon_xz
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            d = b - a
            L = math.hypot(*d)
            if L < 0.35:
                continue
            n = np.array([-d[1], d[0]]) / L
            out.append((f"R{room.id}.W{i+1}", n, float(n @ a)))
    return out


def detect(ir: CaptureIR, rooms, floor_y: float, *,
           protrusion_m: float = PROTRUSION_M) -> list[DamageRegion]:
    """Find regions where the measured surface departs from its wall plane."""
    if ir.points is None or len(ir.points) == 0 or not rooms:
        return []

    pts = ir.points
    xz = pts[:, [0, 2]]
    height = pts[:, 1] - floor_y
    regions: list[DamageRegion] = []

    for surface_id, normal, offset in _wall_planes(ir, rooms, floor_y):
        signed = xz @ normal - offset
        near = np.abs(signed) < WALL_BAND_M
        # Only the part of the wall that is at usable height; skirting and ceiling junctions
        # are structurally different and generate false positives.
        near &= (height > 0.15) & (height < 2.40)
        if near.sum() < 400:
            continue

        # Along-wall coordinate, so the wall can be rasterised as a flat image.
        along = xz[near] @ np.array([normal[1], -normal[0]])
        h = height[near]
        dev = np.abs(signed[near])

        cell = 0.03
        u = ((along - along.min()) / cell).astype(int)
        v = ((h - h.min()) / cell).astype(int)
        if u.max() < 3 or v.max() < 3:
            continue

        acc = np.zeros((v.max() + 1, u.max() + 1), np.float32)
        cnt = np.zeros_like(acc)
        np.add.at(acc, (v, u), dev)
        np.add.at(cnt, (v, u), 1.0)
        mean_dev = np.divide(acc, cnt, out=np.zeros_like(acc), where=cnt > 0)

        mask = ((mean_dev > protrusion_m) & (cnt > 0)).astype(np.uint8)
        if mask.sum() < 4:
            continue
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA] * cell ** 2
            if not (MIN_REGION_M2 <= area <= MAX_REGION_M2):
                continue
            w = stats[i, cv2.CC_STAT_WIDTH] * cell
            ht = stats[i, cv2.CC_STAT_HEIGHT] * cell
            bottom = h.min() + stats[i, cv2.CC_STAT_TOP] * cell
            sel = labels == i
            peak = float(mean_dev[sel].max())
            # Blistered plaster lifts by millimetres. A sofa, a radiator or a wardrobe stands
            # off the wall by tens of centimetres, and so does a wall the polygon simplified
            # through. Anything that deep is furniture or a fitting error, not a surface defect.
            if peak > MAX_PROTRUSION_M:
                continue
            cls, conf = classify_by_shape(w, ht, area, peak)
            regions.append(DamageRegion(
                id=f"D{len(regions)+1}", surface_id=surface_id,
                damage_class=cls, class_source="shape", class_confidence=conf,
                width_m=float(w), height_m=float(ht), area_m2=float(area),
                height_above_floor_m=float(bottom),
                mean_protrusion_m=float(mean_dev[sel].mean()),
                max_protrusion_m=float(mean_dev[sel].max())))

    regions.sort(key=lambda r: -r.area_m2)
    return regions[:40]
