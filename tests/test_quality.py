"""Scene-condition detection, including the part that is deliberately switched off."""
from __future__ import annotations

import numpy as np

from scanplan import quality
from scanplan.geometry.walls import Grid


def _grid(w=200, h=200):
    return Grid(data=np.zeros((h, w), np.float32), origin=np.array([0.0, 0.0]), cell_m=0.02)


class _IR:
    def __init__(self, points, traj):
        self.points = points
        self._traj = traj

    @property
    def trajectory(self):
        return self._traj


def test_mirror_flag_is_never_raised_while_uncalibrated():
    """Two geometric tests were built and neither separates a reflection from ordinary
    geometry. Until one does, the flag stays down rather than being tuned to three examples."""
    assert quality.MIRROR_DETECTION_CALIBRATED is False
    g = _grid()
    cov = np.ones(g.shape, np.uint8)
    pts = np.random.default_rng(0).uniform(0, 3, (5000, 3))
    ir = _IR(pts, np.zeros((10, 3)))
    sc = quality.assess(ir, [], coverage=cov, grid=g)
    assert sc.mirror_or_glass is False


def test_the_uncalibrated_metric_is_still_reported():
    """Switching the flag off must not throw the measurement away."""
    g = _grid()
    cov = np.zeros(g.shape, np.uint8)
    cov[50:150, 50:150] = 1
    pts = np.column_stack([np.full(500, 3.5), np.zeros(500), np.full(500, 3.5)])
    sc = quality.assess(_IR(pts, np.zeros((5, 3))), [], coverage=cov, grid=g)
    assert "beyond_envelope_pct_uncalibrated" in sc.detail


def test_warning_says_mirrors_are_not_detected():
    sc = quality.assess(_IR(np.zeros((10, 3)), np.zeros((5, 3))), [],
                        coverage=np.ones((50, 50), np.uint8), grid=_grid(50, 50))
    codes = [w["code"] for w in sc.warnings()]
    assert "MIRROR_DETECTION_UNCALIBRATED" in codes


def test_floor_holes_under_the_walked_path_flag_a_wet_floor():
    """The camera walked there, so there is floor there. If coverage disagrees, the surface
    did not return the beam."""
    g = _grid()
    cov = np.zeros(g.shape, np.uint8)
    traj = np.column_stack([np.linspace(0.5, 3.0, 50), np.full(50, 1.5), np.full(50, 1.0)])
    sc = quality.assess(_IR(np.zeros((10, 3)), traj), [], coverage=cov, grid=g)
    assert sc.wet_floor is True


def test_complete_floor_coverage_does_not_flag_a_wet_floor():
    g = _grid()
    cov = np.ones(g.shape, np.uint8)
    traj = np.column_stack([np.linspace(0.5, 3.0, 50), np.full(50, 1.5), np.full(50, 1.0)])
    sc = quality.assess(_IR(np.zeros((10, 3)), traj), [], coverage=cov, grid=g)
    assert sc.wet_floor is False


def test_conditions_serialise_for_the_contract():
    sc = quality.SceneConditions(wet_floor=True, detail={"floor_hole_pct": 40.0})
    d = sc.as_dict()
    for key in ("mirror", "glass", "wet_floor", "low_light"):
        assert key in d
