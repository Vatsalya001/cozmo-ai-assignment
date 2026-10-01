"""The two-walk comparison: the false pass it exposed, and the excuse it later removed.

G-REPEAT and G-OPEN were first reported NOT MEASURED with the reason "needs per-wall
correspondence". That was true and it was also an excuse: no attempt had been made to find out
how badly correspondence fails, and the answer mattered more than either gate.

The first pass showed that G-REPEAT-ROOMS, reported MET at "5 vs 5", is a count coincidence,
and then declared the per-wall gate NOT MEASURABLE on two grounds: no common frame, no common
decomposition. The second pass kept the first finding and removed the first ground -- the frame
was recoverable by registering the two floor-coverage masks, so the gate is now measured and
failing rather than unmeasured.

These tests hold both corrections in place. The temptations they guard against are specific:
quietly dropping the room caveat would restore a clean MET, and quietly restoring NOT MEASURABLE
would hide a bad number behind a word.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "bench" / "results" / "same_flat.json"
GATES = ROOT / "bench" / "results" / "gates.json"


@pytest.fixture(scope="module")
def same_flat():
    assert RESULT.is_file(), "run bench/same_flat.py"
    return json.loads(RESULT.read_text())


def test_the_two_walks_agree_on_footprint_and_not_on_rooms(same_flat):
    """The finding in one assertion: total area repeats, its division into rooms does not."""
    foot = same_flat["g_repeat_footprint"]["relative_difference_pct"]
    worst = same_flat["room_correspondence"]["worst_pair_difference_pct"]
    assert foot < 5.0, "the two walks should agree closely on total footprint"
    assert worst > 15.0, (
        "if the room decompositions now DO correspond, this benchmark's central finding has "
        "changed and the G-REPEAT-ROOMS caveat should be revisited deliberately")
    assert same_flat["room_correspondence"]["pairing_is_credible"] is False


def test_the_room_count_match_is_reported_as_counts_only(same_flat):
    """The counts do match. Saying so without saying what it omits is the problem."""
    rc = same_flat["room_correspondence"]
    assert rc["counts_match"] is True
    assert "COUNTS match while the decompositions do not" in rc["finding"]


def test_the_gate_table_carries_the_caveat_not_just_the_benchmark():
    """A caveat buried in a JSON file nobody opens is not a caveat. It has to be in the row a
    reader skims, because the row is what gets quoted."""
    rows = {r["gate"]: r for r in json.loads(GATES.read_text())["rows"]}
    row = rows["G-REPEAT-ROOMS"]
    assert row["status"] == "MET", "the gate asks for the count, and the count matches"
    assert "counts only" in row["result"], (
        "G-REPEAT-ROOMS reads MET; the result string must say that only the counts matched, "
        "or the table overstates what was measured")


# --- the registration, and the gate it unblocked ------------------------------------

def test_the_two_walks_are_registered_into_one_frame_unambiguously(same_flat):
    """Registration is the whole basis of everything below it, so its own quality has to be
    reported and checked. The number that matters is the separation from the best WRONG fit:
    each walk is yaw-aligned modulo 90 degrees, so a quarter-turn error would otherwise look
    plausible."""
    reg = same_flat["registration"]
    away = next(v for k, v in reg["yaw_landscape"].items() if k.startswith("best_at_least"))
    assert reg["fit"]["coverage_iou"] > 0.6, (
        "a coverage IoU this low would mean the two walks did not register, and nothing "
        "downstream of it could be trusted")
    assert reg["fit"]["coverage_iou"] > away["coverage_iou"] + 0.1, (
        "the fit must beat the best fit 10 degrees away by a clear margin, or the transform "
        "is a coin toss dressed as a measurement")


def test_the_pairing_does_not_depend_on_the_refinement_stage(same_flat):
    """Two defensible registration objectives are available (coverage only, or coverage then
    walls). If the set of one-to-one room pairs moved between them, the pairing would be an
    artefact of that choice rather than a property of the data."""
    reg = same_flat["registration"]
    pairs = sorted(f"{p['room_a']}/{p['room_b']}"
                   for p in same_flat["g_repeat_per_wall"]["paired_room_dimensions"]["pairs"])
    assert pairs == reg["one_to_one_pairs_under_coverage_only_fit"]


def test_per_wall_repeatability_is_measured_rather_than_declared_unmeasurable(same_flat):
    """The headline must be the reading that needs no room correspondence, because that is the
    one the decomposition disagreement cannot undermine."""
    g = same_flat["g_repeat_per_wall"]
    assert g["status"].startswith("MEASURED")
    w = g["without_room_correspondence"]
    assert "no room correspondence is used or needed" in w["method"]
    assert 0.0 <= w["fraction_within_gate"] <= 1.0
    assert w["gate_met"] is False, (
        "if wall-level repeatability now passes, that is a major change and the gate table, "
        "the technical report and this test should all be revisited together")
    for direction in w["common_coverage_only"].values():
        assert direction["cells"] > 1000, "a handful of cells is not a wall measurement"


def test_the_overlap_matrix_is_published_not_just_its_conclusion(same_flat):
    """The task the pairing performs is exactly the one most easily faked, so the evidence has
    to ship with it: every non-zero room-to-room overlap, with the share each room contributes.
    A reader must be able to see the one-to-many relations for themselves."""
    rc = same_flat["room_correspondence"]
    matrix = rc["registered_overlap_matrix"]
    assert matrix, "the registered overlap matrix must be published"
    for e in matrix:
        assert {"room_a", "room_b", "intersection_m2", "iou", "share_of_a", "share_of_b"} <= \
            set(e)
    dec = rc["decomposition"]
    assert dec["walk_a_rooms_split_across_two_or_more"] or \
        dec["walk_b_rooms_split_across_two_or_more"], (
        "the two walks are known to divide this floor differently; if no room is split across "
        "two any more, the decompositions have converged and the finding needs rewriting")


def test_the_one_to_one_pairs_are_unique_by_construction(same_flat):
    """IoU >= 0.5 is used instead of a tuned threshold because it is self-enforcing: two
    disjoint rooms cannot both reach it against one room. The test is that property -- no room
    appears twice in the pair list."""
    pairs = same_flat["g_repeat_per_wall"]["paired_room_dimensions"]["pairs"]
    assert pairs, "at least one pair must clear the bound, or there is nothing to compare"
    for p in pairs:
        assert p["iou"] >= 0.5
    assert len({p["room_a"] for p in pairs}) == len(pairs)
    assert len({p["room_b"] for p in pairs}) == len(pairs)


def test_the_small_denominator_is_reported_with_the_pass_rate(same_flat):
    """Four dimensions out of a possible fourteen is the honest denominator here, and it is the
    number a reader is most likely to miss. The share of floor area that found a partner has to
    travel with it."""
    d = same_flat["g_repeat_per_wall"]["paired_room_dimensions"]
    assert d["dimensions_compared"] == 2 * d["pairs_one_to_one"]
    assert d["pairs_one_to_one"] < min(d["rooms"].values()), (
        "if every room now pairs one-to-one, the decomposition disagreement is gone and the "
        "whole narrative of this benchmark has changed")
    shares = d["paired_area_share"]
    assert all(0.0 < s < 1.0 for s in shares.values())
    assert d["gate_met"] is False


def test_paired_rooms_report_a_boundary_offset_as_well_as_dimensions(same_flat):
    """Minimum-area-rectangle sides are a proxy for wall lengths and a poor one for a
    non-rectangular room. The boundary offset between the two registered outlines is the
    correspondence-free check on the same pair, so it has to be there to be read against."""
    for p in same_flat["g_repeat_per_wall"]["paired_room_dimensions"]["pairs"]:
        assert p["boundary_offset"]["cells"] > 0
        assert p["boundary_offset"]["median_cm"] > 0
        assert len(p["vertices"]) == 2, (
            "the vertex counts must ship with the dimensions: a 34-sided outline's bounding "
            "rectangle is not a wall length and the reader needs to see that")


def test_openings_are_paired_by_position_rather_than_by_width_rank(same_flat):
    """Rank pairing assumes the Nth widest opening is the same doorway in both walks. With a
    frame, openings can be paired by where they are, which is a claim that can be wrong in a
    visible way -- an unpaired opening -- instead of an invisible one."""
    o = same_flat["g_open"]
    assert "centre position in the registered frame" in o["method"]
    assert o["denominator"] == max(o["openings_found"].values())
    assert o["paired"] + o["unpaired"] == o["denominator"]
    for p in o["pairs"]:
        assert p["centre_distance_m"] <= 0.80, "one door width is the cutoff"
    assert o["gate_met"] is False
    assert o["superseded_rank_pairing"]["denominator"] > o["denominator"], (
        "the rank pairing ran on the document's per-room lists, where each doorway appears "
        "twice; keeping it visible is the point of recording the superseded method")


def test_the_opening_widths_are_implausibly_narrow_for_doorways(same_flat):
    """Not a gate, but it should not go unrecorded: every opening we measure is 0.16-0.52 m,
    while a doorway is 0.6-0.9 m. Whatever G-OPEN's pairing says, the widths themselves are
    too small, and that is a separate defect from their disagreement."""
    widths = [w for walk in same_flat["walks"].values() for w in walk["opening_widths_m"]]
    assert widths, "both walks report openings"
    assert max(widths) < 0.60, (
        "if openings now reach doorway width, this known defect has been fixed and the "
        "technical report's failure-mode list should say so")
