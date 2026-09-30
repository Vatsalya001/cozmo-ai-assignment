"""The intermediate representation every tier produces and the geometry core consumes.

This is the architectural commitment of the project: the three input tiers differ only in
how they populate a CaptureIR. Everything downstream -- layout, error model, export,
benchmarks -- sees only this, so a tier can be swapped or improved without touching the core,
and all three tiers are scored by the same harness.

World frame: gravity-aligned, y up, metres. Camera frame: OpenCV (x right, y down, z forward).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np

Tier = Literal["lidar", "video", "photo"]
Provenance = Literal["lidar_depth", "arkit_vio", "metric_depth_model", "anchor_object", "user_measurement"]


@dataclass(frozen=True)
class Intrinsics:
    """Pinhole intrinsics, OpenCV convention (pixel centres at integer coordinates)."""

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def scaled_to(self, width: int, height: int) -> "Intrinsics":
        sx, sy = width / self.width, height / self.height
        return Intrinsics(self.fx * sx, self.fy * sy,
                          (self.cx + 0.5) * sx - 0.5, (self.cy + 0.5) * sy - 0.5, width, height)

    @property
    def matrix(self) -> np.ndarray:
        return np.array([[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]])


@dataclass
class Frame:
    """One posed view. `depth` and `depth_confidence` are None at the photo tier."""

    index: int
    timestamp: float
    intrinsics: Intrinsics
    world_from_cam: np.ndarray                      # 4x4 SE3
    pose_covariance: Optional[np.ndarray] = None    # 6x6, translation then rotation
    depth_m: Optional[np.ndarray] = None            # (h, w) metres
    depth_confidence: Optional[np.ndarray] = None   # (h, w) 0 low .. 2 high
    image_path: Optional[str] = None

    @property
    def position(self) -> np.ndarray:
        return self.world_from_cam[:3, 3]

    @property
    def rotation(self) -> np.ndarray:
        return self.world_from_cam[:3, :3]


@dataclass
class ScaleEstimate:
    """Metric scale is the axis that actually separates the three tiers, so it is an explicit
    optimised quantity with a stated origin and uncertainty -- never an implicit assumption."""

    value: float = 1.0
    sigma: float = 0.0
    provenance: Provenance = "lidar_depth"
    notes: str = ""


@dataclass
class PlaneHypothesis:
    """A fitted plane: n . x + d = 0, with n unit length."""

    normal: np.ndarray
    offset: float
    inlier_count: int
    rms_residual_m: float
    label: Literal["wall", "floor", "ceiling", "other"] = "other"
    support_extent: Optional[np.ndarray] = None     # (2, 3) min/max of inliers

    @property
    def is_vertical(self) -> bool:
        return abs(float(self.normal[1])) < 0.15


@dataclass
class CaptureIR:
    """Everything the geometry core is allowed to look at."""

    capture_id: str
    tier: Tier
    frames: list[Frame] = field(default_factory=list)
    points: Optional[np.ndarray] = None             # (n, 3) metres, gravity-aligned
    normals: Optional[np.ndarray] = None            # (n, 3)
    point_confidence: Optional[np.ndarray] = None   # (n,)
    planes: list[PlaneHypothesis] = field(default_factory=list)
    scale: ScaleEstimate = field(default_factory=ScaleEstimate)
    gravity: np.ndarray = field(default_factory=lambda: np.array([0.0, -1.0, 0.0]))
    loop_closures: list[tuple[int, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def trajectory(self) -> np.ndarray:
        """Camera positions. Also the only points guaranteed to be inside the property,
        which is what seeds free-space flood fill in the layout stage."""
        return np.array([f.position for f in self.frames]) if self.frames else np.zeros((0, 3))

    def summary(self) -> dict:
        return {
            "capture_id": self.capture_id,
            "tier": self.tier,
            "frames": len(self.frames),
            "points": 0 if self.points is None else int(len(self.points)),
            "planes": len(self.planes),
            "scale": {"value": self.scale.value, "sigma": self.scale.sigma,
                      "provenance": self.scale.provenance},
            "loop_closures": len(self.loop_closures),
            "warnings": list(self.warnings),
        }
