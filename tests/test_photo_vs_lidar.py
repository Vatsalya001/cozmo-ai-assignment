"""G-WALL-PHOTO against the LiDAR reference, and the two errors it separates.

This gate read NOT MEASURED because "no reference exists for these folders". Half true, and it
gave up too early: the folders are stills cut from a walked capture at known frame indices, and
that capture has measured LiDAR depth, so a reference was available the whole time.

The result is 0 of 6 within 8%, median error 77%. What makes it useful rather than merely bad is
the second reference. The photo tier sees six stills while the segment holds ~180 frames, so an
obvious objection is that it is being punished for coverage rather than for accuracy. Measuring
LiDAR on *the same six frames* answers it: the reference still gives 4.2-7.6 m where the tier
reports 1.8-2.1 m. The inferred depth under-estimates scale by 3-4x, and coverage is not the
explanation.

These tests keep that second reference in place, because without it the headline number has an
easy excuse attached.
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
    """The finding, asserted: restricting the reference to exactly the stills' own frames does
    NOT rescue the tier. If it ever does, the diagnosis changes from inferred depth being wrong
    to six photographs not covering a room, and the write-up must change with it."""
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


def test_extent_is_compared_rather_than_named_walls(pvl):
    """Unposed stills carry no wall identities. Matching each photo dimension to whichever
    LiDAR wall is nearest would flatter whoever reports more walls."""
    assert "named walls" in pvl["method"]
    quantities = {r["quantity"] for r in pvl["rows"] if "quantity" in r}
    assert quantities <= {"width_m", "depth_m", "area_m2"}
