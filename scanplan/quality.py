"""Scene conditions the brief names explicitly: mirrors, glass, wet-look floors, low light.

Each is detected from what the sensor already recorded, with no model involved.

- **Mirrors and glass** are NOT reliably detected here, and the flag is disabled. Two
  geometric tests were built and both failed, for the same reason: they cannot separate a
  reflection from ordinary geometry. Testing points against room polygons reported 19-30% of
  every capture as mirrored, because rooms under-split and a fifth of a real building falls
  outside them. Testing against the floor-coverage envelope still reported 10-13%, because
  ceiling points, the walls themselves, and floor hidden under furniture all legitimately sit
  outside a floor envelope. There is no threshold that separates the two, so no threshold is
  asserted. The measured fraction is still reported, marked uncalibrated, and the capture
  protocol tells the operator to approach mirrors at an angle.
- **Wet or glossy floors** scatter the beam away from the sensor, leaving holes in floor
  coverage where geometry says floor must be — under the camera's own path, which it walked.
- **Low light** is read from the RGB stream, which is recorded anyway.

These are reported as warnings, not corrected. Geometry near a mirror is wrong in a way no
amount of filtering repairs: the measurement is real, it is just of a room that is not there.
Saying so is worth more than silently deleting the points and producing a plan that looks
clean and has a hole in it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

cv2.setNumThreads(0)

BEYOND_WALL_M = 0.45        # further than this behind a wall is not measurement noise
# No value works. At 0.004 every capture flags; raising it until these three stop flagging
# would be fitting a constant to three examples and calling it a detector. The metric is
# reported, the flag is not raised. See the module docstring.
MIRROR_DETECTION_CALIBRATED = False
LOW_LIGHT_LUMA = 60.0       # mean 0-255 luminance below which a frame counts as dark
LOW_LIGHT_FRACTION = 0.30   # fraction of dark frames that raises the flag
FLOOR_HOLE_FRACTION = 0.18  # fraction of the walked path with no floor beneath it


@dataclass
class SceneConditions:
    mirror_or_glass: bool = False
    wet_floor: bool = False
    low_light: bool = False
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"mirror": self.mirror_or_glass, "glass": self.mirror_or_glass,
                "wet_floor": self.wet_floor, "low_light": self.low_light,
                **{f"_{k}": v for k, v in self.detail.items()}}

    def warnings(self) -> list[dict]:
        out = []
        if not MIRROR_DETECTION_CALIBRATED:
            out.append({
                "code": "MIRROR_DETECTION_UNCALIBRATED", "severity": "warning",
                "message": f"mirrors and glass are NOT detected. Two geometric tests were built "
                           f"and neither separates a reflection from ordinary geometry; "
                           f"{self.detail.get('beyond_envelope_pct_uncalibrated', 0):.1f}% of "
                           f"points sit outside the floor envelope here, which is normal for "
                           f"ceilings and occluded floor. Geometry near any mirror in this "
                           f"capture is wrong and unflagged. The capture protocol asks the "
                           f"operator to approach mirrors at an angle"})
        if self.wet_floor:
            out.append({
                "code": "WET_OR_GLOSSY_FLOOR", "severity": "warning",
                "message": f"floor is missing beneath {self.detail.get('floor_hole_pct', 0):.0f}% "
                           f"of the path the camera actually walked, which is the signature of a "
                           f"wet or glossy surface scattering the beam away. Floor area is "
                           f"under-reported there"})
        if self.low_light:
            out.append({
                "code": "LOW_LIGHT", "severity": "warning",
                "message": f"{self.detail.get('dark_pct', 0):.0f}% of sampled frames are dark "
                           f"(mean luminance below {LOW_LIGHT_LUMA:.0f}/255). Depth degrades in "
                           f"low light and openings are more likely to be missed"})
        return out


def _beyond_envelope_fraction(points: np.ndarray, coverage: np.ndarray, grid) -> float:
    """Fraction of points sitting well outside the building envelope.

    The envelope is the measured floor coverage, dilated by the threshold. Room polygons are
    deliberately NOT used for this: rooms under-split and under-cover, so a fifth of a real
    building falls outside them and the test then reports every capture as full of mirrors --
    which it did, at 19 to 30 percent, on three captures that have no mirror problem.

    Outside the envelope is a different claim entirely: the sensor returned a surface where
    there is no floor beneath it and never was.
    """
    if points is None or len(points) == 0 or coverage is None or grid is None:
        return 0.0

    grow = int(BEYOND_WALL_M / grid.cell_m) | 1
    envelope = cv2.dilate(coverage, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow, grow)))
    # Fill enclosed voids so unobserved interior floor is not mistaken for outside.
    padded = cv2.copyMakeBorder(envelope, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = padded.copy()
    cv2.floodFill(ff, np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8), (0, 0), 1)
    envelope = (envelope | (1 - ff)[1:-1, 1:-1]).astype(np.uint8)

    px = grid.to_pixel(points[:, [0, 2]])
    inside_grid = ((px[:, 1] >= 0) & (px[:, 1] < envelope.shape[0]) &
                   (px[:, 0] >= 0) & (px[:, 0] < envelope.shape[1]))
    outside = np.ones(len(px), bool)
    outside[inside_grid] = envelope[px[inside_grid, 1], px[inside_grid, 0]] == 0
    return float(outside.mean())


def _low_light_fraction(video_path, samples: int = 24) -> float | None:
    """Fraction of sampled RGB frames that are dark."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return None

    dark = seen = 0
    for i in np.linspace(0, max(total - 1, 0), samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, frame = cap.read()
        if not ok:
            continue
        seen += 1
        if cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean() < LOW_LIGHT_LUMA:
            dark += 1
    cap.release()
    return dark / seen if seen else None


def _floor_hole_fraction(coverage: np.ndarray, grid, trajectory_xz: np.ndarray) -> float:
    """Fraction of the camera's own path with no floor measured beneath it.

    The camera walked there, so there is floor there. If coverage says otherwise, the surface
    did not return the beam.
    """
    if coverage is None or len(trajectory_xz) == 0:
        return 0.0
    px = grid.to_pixel(trajectory_xz)
    ok = ((px[:, 1] >= 0) & (px[:, 1] < coverage.shape[0]) &
          (px[:, 0] >= 0) & (px[:, 0] < coverage.shape[1]))
    if not ok.any():
        return 0.0
    under = coverage[px[ok, 1], px[ok, 0]]
    return float((under == 0).mean())


def assess(ir, rooms, coverage=None, grid=None, video_path=None) -> SceneConditions:
    sc = SceneConditions()

    beyond = _beyond_envelope_fraction(ir.points, coverage, grid)
    sc.detail["beyond_envelope_pct_uncalibrated"] = round(beyond * 100, 2)
    # Reported, never asserted: see the module docstring for the two tests that failed.
    sc.mirror_or_glass = False if not MIRROR_DETECTION_CALIBRATED else beyond > 0.004

    if coverage is not None and grid is not None:
        hole = _floor_hole_fraction(coverage, grid, ir.trajectory[:, [0, 2]])
        sc.detail["floor_hole_pct"] = round(hole * 100, 1)
        sc.wet_floor = hole > FLOOR_HOLE_FRACTION

    if video_path is not None:
        dark = _low_light_fraction(video_path)
        if dark is not None:
            sc.detail["dark_pct"] = round(dark * 100, 1)
            sc.low_light = dark > LOW_LIGHT_FRACTION

    return sc
