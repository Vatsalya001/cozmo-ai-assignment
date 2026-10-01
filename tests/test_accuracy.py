"""Accuracy against a room whose true size is known exactly.

These are the tests that matter. Everything else checks that code runs; these check that the
numbers are right, on geometry we constructed and therefore cannot be wrong about.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from scanplan.geometry import planes, regularize, rooms as rooms_mod, walls


def test_floor_is_found_at_the_right_height(synthetic_ir):
    """The camera walks at 1.50 m, so the floor must sit 1.50 m below it."""
    floor, _ = planes.floor_and_ceiling(synthetic_ir.points, synthetic_ir.trajectory[:, 1])
    assert floor is not None
    assert floor.height_m == pytest.approx(0.0, abs=0.02)
    assert floor.rms_m < 0.02, "a synthetic floor is exactly flat; a large rms means a bug"


def test_ceiling_height_within_two_centimetres(synthetic_room, synthetic_ir):
    """G-CEIL asks for 1.5 cm on real captures. On noiseless synthetic data we should do
    better, and anything worse points at the fit rather than at the sensor."""
    floor, ceiling = planes.floor_and_ceiling(synthetic_ir.points, synthetic_ir.trajectory[:, 1])
    assert ceiling is not None, "the capture sweeps up to the ceiling, so it must be found"
    height, sigma = planes.ceiling_height(floor, ceiling)
    assert height == pytest.approx(synthetic_room["ceiling_m"], abs=0.02)


def test_ceiling_interval_carries_the_residual_bias(synthetic_ir):
    """The interval must not collapse just because there are many points. Averaging 250,000
    samples gives a standard error near zero, which would be confident garbage. The floor is
    now what the measured bias correction leaves unexplained, not a guessed allowance."""
    floor, ceiling = planes.floor_and_ceiling(synthetic_ir.points, synthetic_ir.trajectory[:, 1])
    _, sigma = planes.ceiling_height(floor, ceiling)
    assert sigma >= planes.RESIDUAL_DEPTH_BIAS_M, "sigma must not fall below the residual bias"
    assert sigma < 0.05


def test_the_depth_bias_correction_is_actually_applied(synthetic_room):
    """The fixture writes depth 18 mm short, exactly as the real device does. If the loader
    stopped correcting it, this is the test that notices."""
    import numpy as np
    from scanplan.ingest import stray
    cap = stray.StrayCapture(synthetic_room["path"])
    raw = cap._png("depth", 0).astype(float) / 1000.0
    corrected = cap.depth_m(0)
    delta = (corrected - raw)[raw > 0]
    assert np.allclose(delta, stray.DEPTH_BIAS_CORRECTION_M, atol=1e-6)


def _single_room(ir):
    floor, _ = planes.floor_and_ceiling(ir.points, ir.trajectory[:, 1])
    grid = walls.density(ir.points, floor.height_m)
    mask = walls.wall_mask(grid)
    coverage = walls.floor_coverage(ir.points, floor.height_m, grid)
    free = (coverage & ~cv2.dilate(mask, np.ones((3, 3), np.uint8)).astype(bool)).astype(np.uint8)
    labels = rooms_mod.split_rooms(free, grid)
    found = rooms_mod.polygons(labels, grid)
    assert found, "a box room must produce at least one room"
    return max(found, key=lambda r: r.area_m2), grid


def test_floor_area_within_ten_percent(synthetic_room, synthetic_ir):
    room, _ = _single_room(synthetic_ir)
    truth = synthetic_room["area_m2"]
    assert room.area_m2 == pytest.approx(truth, rel=0.10), (
        f"expected about {truth:.2f} m2, measured {room.area_m2:.2f} m2")


def test_floor_area_is_never_larger_than_truth(synthetic_room, synthetic_ir):
    """Coverage-based area can only under-report: it is floor we actually saw. Over-reporting
    would mean the pipeline is inventing floor, which is the failure we chose to design out."""
    room, _ = _single_room(synthetic_ir)
    assert room.area_m2 <= synthetic_room["area_m2"] * 1.02


def test_room_is_not_a_hundred_sided_blob(synthetic_ir):
    """A rectangular room must come back with few corners. Tracing the raw coverage boundary
    gave 179 once, which is arithmetically true of the pixels and useless as a wall length."""
    room, _ = _single_room(synthetic_ir)
    assert len(room.polygon_xz) <= 12


def test_both_room_dimensions_appear_among_the_walls(synthetic_room, synthetic_ir):
    """A rectangle has two walls of each length, so its two *longest* are both the long pair.
    What matters is that each true dimension is matched by some wall."""
    room, _ = _single_room(synthetic_ir)
    lengths = room.wall_lengths()
    for want in (synthetic_room["width_m"], synthetic_room["depth_m"]):
        best = min(lengths, key=lambda L: abs(L - want))
        assert best == pytest.approx(want, rel=0.12), (
            f"no wall matches {want:.2f} m; closest was {best:.2f} m, all: "
            f"{[round(L, 2) for L in sorted(lengths, reverse=True)]}")


def test_room_extent_matches_the_true_size(synthetic_room, synthetic_ir):
    """The polygon's bounding box is the room's size, independent of how the outline was
    split into segments."""
    room, _ = _single_room(synthetic_ir)
    span = room.polygon_xz.max(axis=0) - room.polygon_xz.min(axis=0)
    got = sorted(span, reverse=True)
    want = sorted([synthetic_room["width_m"], synthetic_room["depth_m"]], reverse=True)
    for g, w in zip(got, want):
        assert g == pytest.approx(w, rel=0.12), f"extent {g:.2f} m vs expected {w:.2f} m"


def test_rectify_straightens_without_moving_far(synthetic_ir):
    room, _ = _single_room(synthetic_ir)
    before = room.polygon_xz
    after = regularize.rectify(before)
    assert regularize.polygon_area(after) == pytest.approx(
        regularize.polygon_area(before), rel=0.08), "rectifying must not resize the room"


def test_rectify_leaves_a_genuinely_diagonal_wall_alone():
    """A 30-degree wall is not noise. Snapping it would make the plan tidy and wrong, which
    the brief penalises harder than being visibly rough."""
    poly = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [2.0, 4.15], [0.0, 3.0]])
    out = regularize.rectify(poly, tolerance_m=0.08)
    diagonal = out[np.argmin(np.abs(out[:, 0] - 2.0))]
    assert diagonal[1] == pytest.approx(4.15, abs=0.05), "the diagonal apex must survive"
