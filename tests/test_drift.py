"""Drift correction.

These exist because of a mutation test: replacing the whole of `drift.correct` with a stub
that returns zeros left all 60 other tests passing. G-DRIFT is a gate the brief calls an
automatic fail if unaddressed, and nothing in the suite would have noticed it being switched
off. Every test here fails against that stub.
"""
from __future__ import annotations

import numpy as np
import pytest

from scanplan.ir import CaptureIR, Frame, Intrinsics
from scanplan.slam import drift


def _walk(n=240, *, revisit=True, seconds=24.0):
    """A square loop. With revisit=True it returns to the start, so there is a loop to close."""
    ir = CaptureIR(capture_id="synthetic_walk", tier="lidar")
    K = Intrinsics(200.0, 200.0, 128.0, 96.0, 256, 192)
    side = n // 4
    pts = []
    for i in range(n):
        leg, t = i // side, (i % side) / side
        if leg == 0:   p = (t * 4, 0.0)
        elif leg == 1: p = (4.0, t * 3)
        elif leg == 2: p = (4 - t * 4, 3.0)
        else:          p = (0.0, 3 - t * 3) if revisit else (0.0, 3.0)
        pts.append(p)
    for i, (x, z) in enumerate(pts):
        T = np.eye(4)
        T[:3, 3] = [x, 1.5, z]
        ir.frames.append(Frame(index=i, timestamp=i * seconds / n,
                               intrinsics=K, world_from_cam=T))
    return ir


def test_a_revisiting_walk_yields_loop_closures():
    """A loop that returns to its start must produce closures; zero means the detector is
    not running."""
    ir = _walk(revisit=True)
    r = drift.correct(ir, apply=False)
    assert r.loop_closures > 0
    assert r.submaps >= 2


def test_a_walk_that_never_revisits_reports_no_loop_to_close():
    """And says so, rather than reporting a correction of zero as a success."""
    ir = _walk(revisit=False)
    r = drift.correct(ir, apply=False)
    assert r.loop_closures == 0
    assert r.applied is False
    assert any("revisit" in n or "loop" in n for n in r.notes)


def test_the_method_is_stated_not_blank():
    """G-DRIFT requires the method to be stated; 'poses used as-is' is an automatic fail."""
    r = drift.correct(_walk(), apply=False)
    assert "submap" in r.method and "4-DoF" in r.method
    assert len(r.method) > 40


def test_apply_false_still_computes_the_estimate():
    """The on/off ablation must compare one pipeline against itself, so the estimate has to be
    computed identically either way -- otherwise it compares two different pipelines."""
    ir_on, ir_off = _walk(), _walk()
    a = drift.correct(ir_on, apply=True)
    b = drift.correct(ir_off, apply=False)
    assert a.loop_closures == b.loop_closures
    assert a.submaps == b.submaps
    assert a.applied is True and b.applied is False


def test_applying_actually_moves_the_poses():
    """apply=True must change the trajectory; a no-op that reports a correction is worse than
    no correction, because the ablation then shows a difference that is not there."""
    ir_on, ir_off = _walk(), _walk()
    before = ir_on.trajectory.copy()
    drift.correct(ir_on, apply=True)
    drift.correct(ir_off, apply=False)
    assert not np.allclose(before, ir_on.trajectory, atol=1e-9), "apply=True changed nothing"
    assert np.allclose(before, ir_off.trajectory, atol=1e-9), "apply=False moved the poses"


def test_corrections_stay_small_on_a_clean_walk():
    """A synthetic walk has no drift, so the solver must not invent one."""
    r = drift.correct(_walk(), apply=True)
    assert r.max_shift_m < 0.30, f"invented a {r.max_shift_m:.2f} m correction on a clean walk"


def test_vertical_is_left_alone():
    """Only x, z and yaw are corrected: gravity is measured by the IMU and is not in doubt,
    so optimising height would trade real error against imaginary error."""
    ir = _walk()
    heights_before = ir.trajectory[:, 1].copy()
    drift.correct(ir, apply=True)
    assert np.allclose(heights_before, ir.trajectory[:, 1], atol=1e-9)


def test_an_empty_capture_does_not_crash():
    r = drift.correct(CaptureIR(capture_id="empty", tier="lidar"), apply=True)
    assert r.applied is False and r.loop_closures == 0
