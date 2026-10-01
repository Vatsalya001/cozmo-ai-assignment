"""A-WALL-LIDAR against laser truth, and the distinction the result turns on.

8 of 10 wall-to-wall distances are within max(2 cm, 1%). The gate is not met, and the useful
part is why: where both clouds select the *same* pair of walls it is **8 of 8 within gate,
median 8.1 mm**, and the two failures are our plane-pair selection choosing different walls in
the device cloud than in the laser cloud. Those need completely different fixes, and a reader
cannot tell them apart from the error alone.

It got here through three corrections, each of which moved the number for a different reason:

  6/12, median 24.6 mm   yaw estimated INDEPENDENTLY PER CLOUD, so "distance along x" meant a
                         different direction in each and their difference was not a distance
                         error at all. Both clouds now share one frame, taken from the DEVICE
                         cloud -- never the laser, which would let the reference decide how the
                         measurement is oriented.
  7/12, median 16.4 mm   the shared frame, measured.
  8/10, median 9.8 mm    plane selection now knows ORIENTATION. Density alone cannot tell a wall
                         from a wardrobe side; both deposit a dense 1 cm column along one axis.
                         Per-point normals, a facing test and extent gates took the worst row
                         from 975 mm to 3.4 mm.

The denominator fell from 12 to 10 because one walk has no two wall-sized surfaces facing each
other on either axis. That is a failure to FIND a measurement, not to make one accurately, and
it is recorded per row -- a silently dropped axis shrinks the denominator and reads as a
measurement that happened to pass.
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


def test_both_clouds_are_measured_in_one_shared_frame(wd):
    """The second defect, and the one that made the comparison invalid rather than merely noisy.

    `wall_distances` used to estimate the yaw alignment independently per cloud, so "the distance
    along x" meant a different direction in the device cloud than in the laser cloud. The
    difference between two distances measured along two different axes is not a distance error.
    `walls.dominant_orientations` quantises to 1 degree, and a one-bin disagreement was measured.

    The shared frame must come from the DEVICE cloud. Taking it from the laser would let the
    reference decide how the measurement is oriented, which is a quieter form of fitting to truth.
    """
    scored = [r for r in wd["rows"] if "error_mm" in r]
    assert scored
    for r in scored:
        assert "shared_yaw_deg" in r and "laser_own_yaw_deg" in r, (
            "both the frame used and the laser's own independent estimate must be published, "
            "or a reader cannot see how far apart the two frames would have been")
    assert "DEVICE cloud" in wd["method"] and "never the" in wd["method"]


def test_the_plane_selection_limitation_is_stated_not_filtered(wd):
    """The catastrophic rows come from a raw histogram argmax deciding between near-tied
    parallel surfaces. Dropping those rows would turn a failure into a pass by discarding the
    failures, so the limitation is declared and the denominator left alone."""
    assert "known_limitation" in wd
    assert "argmax" in wd["known_limitation"]
    assert "discarding the failures" in wd["known_limitation"]


def test_each_cloud_selects_its_own_wall_pair(wd):
    """The variant that reached 11/11 MET let the DEVICE choose which two surfaces the laser
    then measured. That is defensible as a definition -- A-WALL-LIDAR is a length gate -- but it
    stops charging us for naming a different valid pair than the laser names, which is a
    relaxation of what the gate penalises introduced by the person reporting the pass. It was
    built, measured, and declined (docs/declined_changes.md section 2).

    This test is the guard. If selection ever becomes shared, the gate's meaning changed and
    that has to be a deliberate, documented decision rather than a quiet improvement.
    """
    src = (ROOT / "bench" / "wall_distance_walks.py").read_text()
    assert "normals=dev_n" in src and "normals=las_n" in src, (
        "both clouds must be handed their OWN normals and select their own planes")
    assert "declined_changes" in src, (
        "the rejected shared-selection variant must stay referenced where the choice is made")


def test_plane_selection_knows_orientation_not_just_density(wd):
    """Density alone cannot tell a wall from a wardrobe side: along one axis both deposit a
    dense 1 cm column. That ambiguity produced a 975 mm error. Every scored plane must now
    carry the extent evidence that admitted it."""
    scored = [r for r in wd["rows"] if "error_mm" in r]
    assert scored
    for r in scored:
        for side in ("device_cover_m", "laser_cover_m", "device_span_m", "laser_span_m"):
            if side in r:
                assert all(v > 0 for v in r[side])


def test_a_rejected_axis_is_reported_not_silently_dropped(wd):
    """An axis with no opposing wall pair is a failure to FIND a measurement, which is different
    from measuring one badly. Both belong in the record: a silently dropped axis shrinks the
    denominator and reads as a measurement that happened to pass."""
    total_rows = len(wd["rows"])
    accounted = sum(1 for r in wd["rows"]
                    if "error_mm" in r or "rejected" in r or "rejected_axis" in r)
    assert accounted == total_rows, "every row must either score or say why it did not"
    assert wd["distances_scored"] + wd["rejected"] <= total_rows + 1


def test_the_gate_threshold_scales_with_the_distance(wd):
    """max(2 cm, 1%): a 2 cm floor on short spans, 1% on long ones."""
    for r in wd["rows"]:
        if "error_mm" not in r:
            continue
        assert r["gate_m"] == pytest.approx(max(0.02, 0.01 * r["laser_m"]), abs=1e-4)
