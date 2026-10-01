"""The two-walk comparison, and the false pass it exposed.

G-REPEAT and G-OPEN were reported NOT MEASURED with the reason "needs per-wall correspondence".
That was true and it was also an excuse: no attempt had been made to find out how badly
correspondence fails, and the answer mattered more than either gate.

It showed that G-REPEAT-ROOMS, reported MET at "5 vs 5", is a count coincidence. Both walks
return five rooms; paired by area rank they are up to 76% apart, and one walk keeps as a single
room roughly what the other splits in two. A reviewer can see it by adding two numbers in the
result, so the gate table must not read as agreement about rooms.

These tests hold that correction in place. The temptation they guard against is specific:
quietly dropping the caveat would restore a clean MET and nobody would notice until it was
noticed by someone else.
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


def test_per_wall_repeatability_is_unmeasurable_with_stated_reasons(same_flat):
    """NOT MEASURED is only honest when it names what was tried. Two reasons, and the second
    is the one that cannot be engineered around."""
    g = same_flat["g_repeat_per_wall"]
    assert len(g["why"]) >= 2
    assert any("no common decomposition" in w for w in g["why"])
    assert "would rest on a correspondence" in g["what_was_not_done"], (
        "the benchmark must record the number it declined to produce, so that declining is a "
        "visible decision rather than an omission")


def test_openings_are_measured_rather_than_left_unmeasured(same_flat):
    """0 of 12 within 2 cm is a bad result and a real one. It replaces a NOT MEASURED that was
    standing in for work not done."""
    o = same_flat["g_open"]
    assert o["denominator"] >= 1
    assert o["gate_met"] is False
    assert o["within_gate"] == 0 or o["fraction"] < 0.85
    assert "rank" in o["caveat"], "the pairing device must travel with the number"


def test_the_opening_widths_are_implausibly_narrow_for_doorways(same_flat):
    """Not a gate, but it should not go unrecorded: every opening we measure is 0.16-0.52 m,
    while a doorway is 0.6-0.9 m. Whatever G-OPEN's pairing says, the widths themselves are
    too small, and that is a separate defect from their disagreement."""
    widths = [w for walk in same_flat["walks"].values() for w in walk["opening_widths_m"]]
    assert widths, "both walks report openings"
    assert max(widths) < 0.60, (
        "if openings now reach doorway width, this known defect has been fixed and the "
        "technical report's failure-mode list should say so")
