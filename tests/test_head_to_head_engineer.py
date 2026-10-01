"""The engineer head-to-head measures what it claims, and its committed numbers are intact.

The benchmark itself is slow -- it builds two 360-frame captures and runs the pipeline twice --
so these tests cover the extraction and scoring logic directly, plus the committed artifacts
that a reviewer would actually read.

The thing most worth guarding is the two-capture design. Running only the capture that models
the sensor as we measured it would be choosing the input that suits us, and the result would
flip from honest to rigged without a single number changing. A test that both captures are
present, and that they disagree about the sensor, keeps that visible.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT))

import head_to_head_engineer as h2he                                         # noqa: E402

RESULT = ROOT / "bench" / "results" / "head_to_head_engineer.json"
OPPONENT = ROOT / "data" / "opponents" / "cozmo-scan.json"


def _doc(area, ceiling, perimeter, poly, rooms=1):
    return {"rooms": [{"floor_area_m2": {"value": area},
                       "ceiling_height_m": {"value": ceiling},
                       "perimeter_m": {"value": perimeter},
                       "polygon": poly}] * rooms}


def test_dimensions_come_from_the_polygon_extent_not_from_named_walls():
    """Two independent implementations share no wall identities, so the bounding box is the
    only well-defined correspondence. A 4x3 room reports 4 as long and 3 as short however
    either side chose to split its outline into segments."""
    got = h2he.dimensions_from(_doc(12.0, 2.5, 14.0,
                                    [[0, 0], [4, 0], [4, 3], [0, 3]]))
    assert got["long dimension"] == pytest.approx(4.0)
    assert got["short dimension"] == pytest.approx(3.0)
    assert got["floor area"] == pytest.approx(12.0)
    assert got["perimeter"] == pytest.approx(14.0)


def test_dimensions_are_taken_from_the_largest_room():
    """A capture that over-splits must not be scored on a cupboard."""
    doc = {"rooms": [
        {"floor_area_m2": {"value": 1.0}, "ceiling_height_m": {"value": 2.4},
         "perimeter_m": {"value": 4.0}, "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]},
        {"floor_area_m2": {"value": 12.0}, "ceiling_height_m": {"value": 2.5},
         "perimeter_m": {"value": 14.0}, "polygon": [[0, 0], [4, 0], [4, 3], [0, 3]]},
    ]}
    assert h2he.dimensions_from(doc)["floor area"] == pytest.approx(12.0)


def test_an_empty_result_yields_no_dimensions_rather_than_raising():
    """A pipeline that found nothing is a result, not a crash."""
    assert h2he.dimensions_from({"rooms": []}) == {}


def test_truth_orders_the_two_room_dimensions():
    t = {"area_m2": 12.0, "ceiling_m": 2.5, "width_m": 3.0, "depth_m": 4.0, "perimeter_m": 14.0}
    got = h2he.truth_of(t)
    assert got["long dimension"] == 4.0 and got["short dimension"] == 3.0


def test_the_two_captures_disagree_about_the_sensor():
    """The design the whole comparison rests on. One models the device as measured (reads
    short), one models an ideal sensor. Collapsing them to a single capture would let us pick
    the input that suits our bias correction without any number changing."""
    biases = {n: c["device_bias_m"] for n, c in h2he.CAPTURES.items()}
    assert len(biases) == 2, "two captures, two positions on the sensor question"
    assert 0.0 in biases.values(), "one capture must model an unbiased sensor"
    assert max(biases.values()) > 0.0, "one must model the measured 18 mm short reading"


def test_the_measured_bias_capture_matches_what_the_benchmark_measured():
    """If bench/depth_bias.py is re-run on more scans and the bias moves, this capture is no
    longer modelling the device and must be updated deliberately."""
    bias = json.loads((ROOT / "bench" / "results" / "depth_bias.json").read_text())
    measured_short_by = -bias["pooled_median_mm"] / 1000.0
    assert h2he.CAPTURES["biased"]["device_bias_m"] == pytest.approx(measured_short_by, abs=5e-4)


def test_the_opponent_is_recorded_with_enough_detail_to_be_checked():
    rec = json.loads(OPPONENT.read_text())
    opp = rec["opponent"]
    for field in ("name", "author", "repo", "commit"):
        assert opp.get(field), f"the opponent record must carry {field}"
    assert set(rec["captures"]) == set(h2he.CAPTURES), (
        "the opponent must be recorded on every capture we score")
    assert "NOT a consumer scanning app" in opp["note"], (
        "the record must say this does not satisfy Part 3, which asks for a consumer app")


def test_the_committed_comparison_scored_every_dimension():
    res = json.loads(RESULT.read_text())
    assert res["dimensions_total"] == len(h2he.DIMENSIONS) * len(h2he.CAPTURES)
    assert res["dimensions_scored"] == res["dimensions_total"], (
        f"{res['dimensions_total'] - res['dimensions_scored']} dimensions went unscored: "
        f"{res.get('notes')}")
    assert res["gate_met"] is True
    assert res["beat_or_tie_pct"] >= 70.0


def test_the_committed_comparison_reports_a_loss_rather_than_a_clean_sweep():
    """Not a vanity check. The predicted consequence of correcting an 18 mm bias is that we
    are WORSE on a sensor that has none, and the ideal capture exists to expose exactly that.
    A 10/10 here would mean the ideal capture had stopped testing anything."""
    res = json.loads(RESULT.read_text())
    lost = [r for r in res["rows"] if r.get("we_beat_or_tie") is False]
    assert lost, "the ideal-sensor capture must be able to beat us, or it is not a control"
    assert any(r["capture"] == "ideal" for r in lost), (
        "the loss should be on the ideal capture, where our bias correction is unwarranted")


def test_the_result_does_not_claim_to_satisfy_part_3():
    """Part 3 asks for a consumer scanning app. Another engineer's submission is not one, and
    quietly letting this fill that slot would be the most tempting dishonesty available here."""
    res = json.loads(RESULT.read_text())
    assert "consumer scanning app" in res["relationship_to_part_3"]
    assert "supplementary" in res["relationship_to_part_3"].lower()
