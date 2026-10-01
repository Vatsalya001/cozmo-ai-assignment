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


def _tape_csv(path: Path, values: dict[str, dict[str, float]]) -> Path:
    path.write_text("")
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["room", "element", "reading1_m", "reading2_m"])
        for room, dims in values.items():
            for el, v in dims.items():
                w.writerow([room, el, f"{v:.3f}", f"{v:.3f}"])
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
    p.write_text("room,element,reading1_m,reading2_m\nR1,left wall,3.600,3.620\n")
    assert h2h.read_tape(p)["R1"]["left wall"] == pytest.approx(3.610)


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
        "R2": {"ceiling height": 2.78, "floor area": 2.80, "perimeter": 5.90},
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
