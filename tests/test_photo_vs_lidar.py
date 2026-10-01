"""G-WALL-PHOTO against the LiDAR reference, and the two errors it separates.

This gate read NOT MEASURED because "no reference exists for these folders". Half true, and it
gave up too early: the folders are stills cut from a walked capture at known frame indices, and
that capture has measured LiDAR depth, so a reference was available the whole time.

The result is 0 of 6 within 8%, median error 75.5%. What makes it useful rather than merely bad
is the second reference. The photo tier sees six stills while the segment holds ~180 frames, so
an obvious objection is that it is being punished for coverage rather than for accuracy.
Measuring LiDAR on *the same six frames* answers it: the reference still gives 4.2-7.6 m where
the tier reports 1.2-1.7 m.

**An earlier version of this file concluded "the inferred depth under-estimates scale by 3-4x".
That was refuted by measurement** -- the inferred depth runs about 1.26x LONG against the LiDAR
depth on these same stills. Chasing it turned up a genuine bug (the floor fit assumed an upright
camera and was fitting a wall), fixing which moved the gate by 1.3 points. What survives is
structural: with no poses the tier cannot merge views, so its box is bounded by one viewpoint's
reach, measured at 2.2-2.9 m against the posed reference's 4.2-4.7 m.

These tests keep the second reference in place, and pin the orientation fix, because without
them the headline number has an easy excuse attached and the bug can come back.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "bench" / "results" / "photo_vs_lidar.json"


@pytest.fixture(scope="module")
def pvl():
    assert RESULT.is_file(), "run bench/photo_vs_lidar.py"
    return json.loads(RESULT.read_text())


def test_the_reference_is_called_a_reference_and_not_truth(pvl):
    """Nobody has taped this property. Calling the LiDAR side truth would overstate it, and the
    gate's +-8% is applied against a reference."""
    assert "not truth" in pvl["not_truth"].lower() or "not ground truth" in pvl["not_truth"]
    # The anchoring claim matters as much as the disclaimer: the reference is not truth, but it
    # is not arbitrary either, because the same pipeline is within 15 mm of laser depth.
    assert "15 mm" in pvl["not_truth"] and "laser" in pvl["not_truth"]
    assert "LiDAR" in pvl["reference"] and "frames" in pvl["reference"]


def test_both_references_are_reported(pvl):
    """Full segment, and the same six frames the stills came from. The second is what rules out
    coverage as the explanation."""
    kinds = {r.get("reference_kind") for r in pvl["rows"] if "reference_kind" in r}
    assert "the whole segment of the walk" in kinds
    assert "same six frames as the stills" in kinds


def test_only_the_full_segment_rows_score_the_gate(pvl):
    """The six-frame comparison is diagnostic, not the gate. Mixing them would double-count
    each segment and make the denominator meaningless."""
    scored = [r for r in pvl["rows"] if "within_gate" in r and r.get("scored_for_gate", True)]
    assert pvl["scored"] == len(scored)
    for r in pvl["rows"]:
        if r.get("reference_kind") == "same six frames as the stills":
            assert r["scored_for_gate"] is False


def test_the_photo_tier_under_reports_on_the_same_six_frames_too(pvl):
    """Restricting the reference to exactly the stills' own frames does NOT rescue the tier.

    This test's original docstring said the conclusion was "inferred depth being wrong". That
    was measured and refuted: the inferred depth runs about 1.26x LONG against the LiDAR depth
    on these same stills. What survives is narrower and structural -- with no poses the tier
    cannot merge views, so its box is bounded by one viewpoint's reach (2.2-2.9 m measured)
    while the six-frame posed reference spans 4.2-4.7 m.
    """
    same = [r for r in pvl["rows"]
            if r.get("reference_kind") == "same six frames as the stills"]
    assert same, "the six-frame reference must be computed"
    for r in same:
        assert r["relative_error_pct"] < -20.0, (
            f"{r['segment']} {r['quantity']}: {r['relative_error_pct']:+.1f}% against the "
            f"six-frame reference. The documented finding is a large under-report; a small one "
            f"would mean coverage, not depth, is the problem")


def test_the_gate_fails_and_the_number_is_given(pvl):
    assert pvl["gate_met"] is False
    assert pvl["within_gate"] == 0
    assert pvl["median_abs_error_pct"] > 8.0


def test_the_floor_fit_no_longer_assumes_an_upright_camera(pvl):
    """The bug the three wrong diagnoses were hiding.

    `_level_to_floor` required the floor normal within 32 degrees of camera-y. On the frames
    this photo set is cut from, camera-down is 92.8-93.8 degrees from world-down -- the phone
    was held turned -- so the fit accepted a plane normal to camera-y, which is a WALL, and
    levelled the room against it. A landscape photograph of a room is ordinary input.

    The replacement identifies a floor by geometry with no axis assumption: the large plane
    with most of the room on ONE side of it. A wall fails that test because a room straddles it.
    """
    from scanplan.ingest import photos
    src = __import__("inspect").getsource(photos._level_to_floor)
    assert "abs(n[1]) < 0.85" not in src, (
        "the camera-upright assumption is back; a rotated photograph will have a wall fitted "
        "as its floor and the room levelled against it")
    assert photos.FLOOR_SIDE_FRACTION >= 0.5, (
        "the floor test is 'most of the room on one side'; below 0.5 it stops distinguishing "
        "a floor from a wall at all")


def test_extent_is_compared_rather_than_named_walls(pvl):
    """Unposed stills carry no wall identities. Matching each photo dimension to whichever
    LiDAR wall is nearest would flatter whoever reports more walls."""
    assert "named walls" in pvl["method"]
    quantities = {r["quantity"] for r in pvl["rows"] if "quantity" in r}
    assert quantities <= {"width_m", "depth_m", "area_m2"}
