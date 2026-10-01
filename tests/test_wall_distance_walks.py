"""A-WALL-LIDAR against laser truth, and the distinction the result turns on.

6 of 12 wall-to-wall distances are within max(2 cm, 1%). The gate is not met, and the useful
part is why: where both clouds select the *same* pair of walls the median error is 7.5 mm, and
the three worst rows (168, 198 and 948 mm) are our plane-pair selection choosing different
walls in the device cloud than in the laser cloud. Those two failures need completely different
fixes, and a reader cannot tell them apart from the error alone.

So the coordinates of the chosen planes are published per row, and the gate denominator stays
the full set -- picking the wrong walls is our error too, not an excuse to shrink the sample.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "bench" / "results" / "wall_distance_walks.json"


@pytest.fixture(scope="module")
def wd():
    assert RESULT.is_file(), "run bench/wall_distance_walks.py"
    return json.loads(RESULT.read_text())


def test_the_gate_is_scored_on_every_distance_not_just_the_easy_ones(wd):
    """The denominator must be all measured distances. Scoring only the rows where our own
    plane selection agreed would turn a failure into a pass by discarding the failures."""
    scored = [r for r in wd["rows"] if "error_mm" in r]
    assert wd["total"] == len(scored)
    same = wd.get("where_both_clouds_chose_the_same_walls", {})
    assert same.get("distances", 0) < wd["total"], (
        "if every row now agrees on which walls to use, the sub-result has become the gate and "
        "the distinction this file exists to protect no longer applies")
    assert wd["within_gate"] <= same.get("within_gate", 0) + (wd["total"] - same["distances"])


def test_every_row_publishes_where_it_put_the_two_planes(wd):
    """Without these coordinates a 948 mm error is indistinguishable from a 948 mm sensor
    error, which would be an extraordinary claim about a LiDAR phone."""
    for r in wd["rows"]:
        if "error_mm" not in r:
            continue
        assert len(r["device_at"]) == 2 and len(r["laser_at"]) == 2
        assert isinstance(r["same_walls"], bool)


def test_the_large_errors_are_correspondence_failures_not_sensor_errors(wd):
    """The claim in the write-up, asserted against the data: every row off by more than 10 cm
    is a row where the two clouds disagreed about which walls they were measuring."""
    big = [r for r in wd["rows"] if "error_mm" in r and abs(r["error_mm"]) > 100]
    assert big, "the finding describes outliers; if none remain, revisit the write-up"
    for r in big:
        assert r["same_walls"] is False, (
            f"{r['video_id']} {r['axis']}: {r['error_mm']:.0f} mm error while both clouds chose "
            f"the same walls. That would be a real sensor error of that size, which is a very "
            f"different and much worse finding than the one documented")


def test_where_correspondence_holds_the_sensor_is_good(wd):
    """The positive half of the result, and the reason the gate failing is not the whole story:
    on matched walls the agreement is single-digit millimetres."""
    same = wd["where_both_clouds_chose_the_same_walls"]
    assert same["median_abs_error_mm"] < 20.0


def test_the_bias_correction_is_held_out(wd):
    assert wd["bias_correction"] == "leave-one-venue-out"
    for r in wd["rows"]:
        if "error_mm" in r:
            assert r["applied_offset_mm"] != 0.0


def test_the_benchmark_states_what_it_does_not_measure(wd):
    """It measures the sensor and the fusion through our plane fitting. It does NOT measure the
    wall segments `scanplan run` emits, which still have no truth."""
    assert "layout" in wd["does_not_measure"]
    assert "taped" in wd["does_not_measure"] or "tape" in wd["does_not_measure"]


def test_the_gate_threshold_scales_with_the_distance(wd):
    """max(2 cm, 1%): a 2 cm floor on short spans, 1% on long ones."""
    for r in wd["rows"]:
        if "error_mm" not in r:
            continue
        assert r["gate_m"] == pytest.approx(max(0.02, 0.01 * r["laser_m"]), abs=1e-4)
