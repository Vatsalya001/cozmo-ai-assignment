"""The head-to-head scores correctly the moment its two missing inputs exist.

Part 3 is worth 10% of the brief and currently reports PENDING: it needs tape ground truth and
a capture of our own two rooms, and neither exists. So the comparison has never run with data,
and code that has never run with data is code that does not work yet.

That is a bad position for a deliverable whose inputs might arrive an hour before the deadline.
These tests supply synthetic truth and a synthetic result document, so the scoring path is
exercised end to end now rather than discovered to be broken later. They test the *machinery*,
not the result -- the numbers here are invented and prove nothing about accuracy.

The specific thing being guarded: eight of the fourteen magicplan dimensions are wall and door
lengths, and until this was fixed `read_ours` did not extract wall lengths at all. Those eight
would have come back `ours_m: None`, dropped silently out of the denominator, and left a gate
computed over six dimensions reporting as though it covered fourteen.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT))

import head_to_head as h2h                                                   # noqa: E402


# The element ids and the `type` column are the real template's, not a convenience shape.
# An earlier version of this helper invented its own columns, so the tests passed while the
# committed template could not have been read at all -- the harness-is-not-the-product failure
# again, this time in a test fixture.
DIM_TO_ELEMENT = {v: k for k, v in h2h.ELEMENT_TO_DIMENSION.items()}


def _tape_csv(path: Path, values: dict[str, dict[str, float]]) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["room", "element", "type", "reading1_m", "reading2_m", "note"])
        for room, dims in values.items():
            for dim, v in dims.items():
                if dim == "ceiling height":
                    # Taped in two parts, as the template instructs; read_tape sums them.
                    w.writerow([room, f"{room}.C1a", "ceiling_part1", "0.450", "0.450", ""])
                    w.writerow([room, f"{room}.C1b", "ceiling_part2",
                                f"{v - 0.45:.3f}", f"{v - 0.45:.3f}", ""])
                    continue
                if dim in ("floor area", "perimeter"):
                    continue          # derived by read_tape, never taped directly
                if dim == "_walls":
                    # R2's walls are unnamed in the template on purpose: magicplan publishes no
                    # bathroom wall dimensions, so they only feed the derived area and
                    # perimeter. Written here so that derivation is exercised.
                    for i, wv in enumerate(v, 1):
                        w.writerow([room, f"{room}.W{i}", "wall", f"{wv:.3f}", f"{wv:.3f}", ""])
                    continue
                if dim == "_door":
                    w.writerow([room, f"{room}.O1", "opening_width",
                                f"{v:.3f}", f"{v:.3f}", ""])
                    continue
                el = DIM_TO_ELEMENT.get(dim)
                if el is None:
                    continue
                kind = "opening_width" if "door" in dim else "wall"
                w.writerow([room, el, kind, f"{v:.3f}", f"{v:.3f}", ""])
    return path


def _result_doc(out_dir: Path, room_id: str, *, area, ceiling, perimeter, walls, openings):
    d = out_dir / f"capture_{room_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps({
        "capture": {"tier": "video", "source_path": "/x/data/own/rooms"},
        "rooms": [{
            "id": room_id,
            "floor_area_m2": {"value": area},
            "ceiling_height_m": {"value": ceiling},
            "perimeter_m": {"value": perimeter},
            "walls": [{"length_m": {"value": v}} for v in walls],
            "openings": [{"width_m": {"value": v}} for v in openings],
        }],
    }))
    return d


def _point_at(monkeypatch, own_dir: Path, out_dir: Path):
    """Run main() against temp inputs instead of the repo's own data and out/ folders."""
    real_read_ours = h2h.read_ours
    monkeypatch.setattr(h2h, "OWN", own_dir)
    monkeypatch.setattr(h2h, "OUT", own_dir / "head_to_head.json")
    monkeypatch.setattr(h2h, "read_ours", lambda: real_read_ours(out_dir))


def test_tape_readings_are_averaged(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("room,element,type,reading1_m,reading2_m,note\n"
                 "R1,R1.W-left,wall,3.600,3.620,\n")
    assert h2h.read_tape(p)["R1"]["left wall"] == pytest.approx(3.610)


def test_the_template_element_ids_all_join_to_a_dimension():
    """The committed template and the comparison code have to agree on names. They did not:
    the template files the bedroom's left wall as `R1.W-left` and the comparison looked for
    `left wall`, so the fieldwork would have been done and every row would still have scored
    zero. This asserts the join exists for every wall and opening the template asks for."""
    import csv as _csv
    # The TRACKED template, not the filled sheet. The filled one is gitignored fieldwork, so
    # asserting against it validated a file no reviewer receives -- and the tracked template
    # turned out to carry two row types the code had never seen (a door height sharing its
    # element id with the door width, and a second ceiling spot).
    template = ROOT / "data" / "own" / "measurements_to_fill.csv"
    assert template.is_file(), "the blank template must be committed; it is the deliverable"
    rows = [r for r in _csv.DictReader(
        l for l in template.read_text().splitlines()
        if not l.lstrip().startswith("#") and l.strip())]
    measured = [r for r in rows if (r.get("type") or "").strip() in ("wall", "opening_width")]
    assert measured, "the template must ask for walls and openings"
    unjoined = [r["element"] for r in measured
                if r["element"] not in h2h.ELEMENT_TO_DIMENSION]
    # R2's four walls are intentionally unnamed: magicplan publishes no bathroom wall
    # dimensions, so they feed the derived area and perimeter rather than a named comparison.
    assert all(e.startswith("R2.W") for e in unjoined), (
        f"these template rows join to nothing: {unjoined}")


def test_a_door_height_cannot_overwrite_its_width(tmp_path):
    """The committed template files a door's clear WIDTH and its HEIGHT under the same element
    id. Keyed by element alone, the height overwrote the width: a 0.78 m doorway would have been
    compared against magicplan as 2.03 m, after the fieldwork was done correctly."""
    p = tmp_path / "m.csv"
    p.write_text("room,element,type,reading1_m,reading2_m,note\n"
                 "R1,R1.O-bottom,opening_width,0.780,0.780,\n"
                 "R1,R1.O-bottom,opening_height,2.030,2.030,\n")
    got = h2h.read_tape(p)["R1"]
    assert got["bottom door width"] == pytest.approx(0.780), (
        "the door WIDTH must survive a height row sharing its element id")
    assert got["_doors"] == [0.780], "only the width counts as a door opening"


def test_two_ceiling_spots_are_averaged_not_added(tmp_path):
    """The template asks for ceiling height at two places at least a metre apart, each in two
    parts. Summing every ceiling_part row added the spots together: 0.45+2.38+0.45+2.38 gave a
    5.66 m ceiling. The parts of one spot are summed; the spots are then averaged."""
    p = tmp_path / "m.csv"
    p.write_text("room,element,type,reading1_m,reading2_m,note\n"
                 "R1,R1.C1a,ceiling_part1,0.450,0.450,\n"
                 "R1,R1.C1b,ceiling_part2,2.380,2.380,\n"
                 "R1,R1.C2a,ceiling_part1,0.450,0.450,\n"
                 "R1,R1.C2b,ceiling_part2,2.400,2.400,\n")
    got = h2h.read_tape(p)["R1"]
    assert got["ceiling height"] == pytest.approx((2.830 + 2.850) / 2, abs=1e-6)
    assert got["_ceiling_spread_m"] == pytest.approx(0.020, abs=1e-6), (
        "two spots disagreeing is information about the ceiling, not noise to hide")


def test_the_tracked_template_is_what_the_benchmark_reads(tmp_path, monkeypatch):
    """A clean clone has only the blank template, because the filled sheet is gitignored
    fieldwork. The benchmark must fall back to it rather than silently finding nothing."""
    (tmp_path / "measurements_to_fill.csv").write_text(
        "room,element,type,reading1_m,reading2_m,note\n"
        "R1,R1.W-left,wall,3.600,3.600,\n")
    monkeypatch.setattr(h2h, "OWN", tmp_path)
    monkeypatch.setattr(h2h, "OUT", tmp_path / "out.json")
    monkeypatch.setattr(h2h, "read_ours", lambda: {})
    assert h2h.main() == 0
    res = json.loads((tmp_path / "out.json").read_text())
    row = [r for r in res["rows"] if r["dimension"] == "left wall"][0]
    assert row["truth_m"] == pytest.approx(3.600), (
        "the blank-template path must be read; otherwise a reviewer who fills in the committed "
        "file gets a comparison that silently found no truth")


def test_ceiling_height_is_summed_from_its_two_taped_parts(tmp_path):
    """A tape buckles above 2 m, so the template splits it. Summing is the code's job, not the
    measurer's, so the raw readings stay auditable."""
    p = tmp_path / "m.csv"
    p.write_text("room,element,type,reading1_m,reading2_m,note\n"
                 "R1,R1.C1a,ceiling_part1,0.450,0.450,\n"
                 "R1,R1.C1b,ceiling_part2,2.380,2.380,\n")
    assert h2h.read_tape(p)["R1"]["ceiling height"] == pytest.approx(2.830)


def test_perimeter_uses_magicplans_convention_on_both_sides(tmp_path):
    """magicplan's stated bedroom perimeter is 13.41 m while its own six wall segments sum to
    15.09 m, and 15.09 - 0.77 - 0.90 = 13.42: it excludes door openings. Comparing our closed
    polygon against that would charge us both door widths as error."""
    p = tmp_path / "m.csv"
    p.write_text("room,element,type,reading1_m,reading2_m,note\n"
                 "R1,R1.W-left,wall,3.000,3.000,\n"
                 "R1,R1.W-right,wall,4.000,4.000,\n"
                 "R1,R1.O-bottom,opening_width,0.800,0.800,\n")
    got = h2h.read_tape(p)["R1"]
    assert got["perimeter"] == pytest.approx(7.0 - 0.8)
    assert got["_perimeter_closed"] == pytest.approx(7.0)
    assert "door" in got["_perimeter_convention"]


def test_a_missing_tape_file_is_empty_not_an_error(tmp_path):
    """The benchmark must still produce its table and name what is missing."""
    assert h2h.read_tape(tmp_path / "nothing.csv") == {}


def test_wall_lengths_reach_the_comparison(tmp_path):
    """The defect this file exists for: walls used not to be extracted at all."""
    _result_doc(tmp_path, "R1", area=13.0, ceiling=2.8, perimeter=13.4,
                walls=[4.1, 3.6, 3.4, 1.8, 1.7, 0.5], openings=[0.9, 0.77])
    got = h2h.read_ours(tmp_path)
    assert got["R1"]["_walls"] == [4.1, 3.6, 3.4, 1.8, 1.7, 0.5], "must be sorted descending"
    assert got["R1"]["_openings"] == [0.9, 0.77]


def test_rank_pairing_matches_longest_to_longest():
    theirs = {"right wall": 4.10, "left wall": 3.62, "bottom wall": 3.44}
    paired = h2h.pair_by_rank(theirs, [4.05, 3.55, 3.40])
    assert paired["right wall"] == 4.05
    assert paired["left wall"] == 3.55
    assert paired["bottom wall"] == 3.40


def test_rank_pairing_uses_each_of_our_walls_exactly_once():
    """A closest-match rule could use one wall for several of theirs, which is how a benchmark
    flatters itself. Rank cannot: it is a permutation."""
    theirs = {"a": 4.0, "b": 3.9, "c": 1.0}
    paired = h2h.pair_by_rank(theirs, [3.95, 3.94, 0.9])
    assert sorted(paired.values()) == [0.9, 3.94, 3.95]


def test_the_whole_comparison_scores_when_both_inputs_exist(tmp_path, monkeypatch):
    """End to end: tape truth plus our output produces a scored gate with a real percentage."""
    truth = {
        "R1": {"left wall": 3.60, "right wall": 4.08, "bottom wall": 3.42,
               "top-left segment": 1.80, "notch depth": 0.50, "top-right segment": 1.68,
               "bottom door width": 0.78, "upper-right door width": 0.91,
               "ceiling height": 2.80, "floor area": 13.10, "perimeter": 13.38},
        # A 1.673 m square bathroom: area 2.80 m2, closed perimeter 6.69 m, and 6.69 - 0.78 =
        # 5.91 under magicplan's door-excluding convention, which is its stated 5.91. Area and
        # perimeter are DERIVED from these walls by read_tape, never taped directly.
        "R2": {"ceiling height": 2.78, "_walls": [1.673, 1.673, 1.673, 1.673], "_door": 0.78},
    }
    _tape_csv(tmp_path / "measurements.csv", truth)
    out_dir = tmp_path / "out"
    # Ours: deliberately very close to truth, so we beat magicplan on most dimensions.
    _result_doc(out_dir, "R1", area=13.11, ceiling=2.801, perimeter=13.37,
                walls=[4.08, 3.60, 3.42, 1.80, 1.68, 0.50], openings=[0.91, 0.78])
    _result_doc(out_dir, "R2", area=2.80, ceiling=2.781, perimeter=5.90, walls=[], openings=[])

    _point_at(monkeypatch, tmp_path, out_dir)
    assert h2h.main() == 0
    res = json.loads((tmp_path / "head_to_head.json").read_text())

    assert res["missing_inputs"] == [], "both inputs were supplied"
    assert res["dimensions_total"] == 14
    assert res["dimensions_scored"] == 14, (
        f"all 14 should score; {res['dimensions_not_scored']} did not: {res['why_not_scored']}")
    assert res["gate_met"] is True
    assert res["beat_or_tie_pct"] >= 70.0
    assert "gate_denominator_note" in res


def test_unequal_wall_counts_are_reported_not_silently_dropped(tmp_path, monkeypatch):
    """If we find a different number of walls than magicplan, rank pairing is invalid. The gate
    must say so per dimension rather than quietly computing over a smaller denominator."""
    truth = {"R1": {"left wall": 3.60, "ceiling height": 2.80, "floor area": 13.10,
                    "perimeter": 13.38}}
    _tape_csv(tmp_path / "measurements.csv", truth)
    out_dir = tmp_path / "out"
    _result_doc(out_dir, "R1", area=13.11, ceiling=2.80, perimeter=13.37,
                walls=[4.0, 3.0], openings=[])          # 2 walls, magicplan reports 6

    _point_at(monkeypatch, tmp_path, out_dir)
    assert h2h.main() == 0
    res = json.loads((tmp_path / "head_to_head.json").read_text())

    wall_rows = [r for r in res["rows"] if r["dimension"] == "left wall"]
    assert wall_rows and "we_beat_or_tie" not in wall_rows[0]
    assert "different geometry" in wall_rows[0]["not_scored_because"]
    assert res["dimensions_not_scored"] > 0
    assert any("magicplan reports" in w for w in res["why_not_scored"])


def test_the_committed_result_declares_the_deviation_and_what_is_missing():
    """Until the inputs exist, the committed artifact must be explicit on both counts rather
    than simply absent -- an absent head-to-head reads as one that was never attempted."""
    res = json.loads((ROOT / "bench" / "results" / "head_to_head.json").read_text())
    assert res["dimensions_total"] == 14
    assert res["dimensions_scored"] == 0
    assert len(res["missing_inputs"]) == 2
    assert "LiDAR tier" in res["declared_deviation"], "the tier deviation must be declared"
