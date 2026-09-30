"""Exports: the plan, the summary, and the one-page report."""
from __future__ import annotations

import json

import pytest

from scanplan import pipeline
from scanplan.export import render


@pytest.fixture(scope="module")
def doc(synthetic_room):
    return pipeline.run(synthetic_room["path"], stride=2)


def test_all_four_artifacts_are_written(doc, tmp_path):
    written = render.write_all(doc, tmp_path)
    for name in ("plan.svg", "summary.md", "report.pdf", "report.png"):
        assert name in written, f"{name} missing from {written}"
        assert (tmp_path / name).stat().st_size > 0


def test_a_report_failure_does_not_lose_the_plan(doc, tmp_path, monkeypatch):
    """The visual report is the artifact a reader opens first, but losing it must not cost
    them the plan and the JSON they already have."""
    import scanplan.export.report as rep
    monkeypatch.setattr(rep, "write_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    written = render.write_all(doc, tmp_path)
    assert "plan.svg" in written and "summary.md" in written
    assert (tmp_path / "plan.svg").stat().st_size > 0
    assert "report_failed.txt" in written


def test_svg_carries_dimensions_not_just_an_outline(doc, tmp_path):
    """A floor plan whose numbers live only in a JSON file beside it is not a floor plan."""
    svg = render.plan_svg(doc)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "<polygon" in svg
    longest = max(w["length_m"]["value"] for r in doc["rooms"] for w in r["walls"])
    assert f"{longest:.2f}" in svg, "the longest wall's length should be drawn on the plan"


def test_summary_states_the_interval_on_the_footprint(doc):
    md = render.summary_md(doc)
    fp = doc["plan"]["footprint_m2"]
    assert f"{fp['value']:.2f}" in md
    assert f"{fp['ci_low']:.2f}" in md, "a value without its interval is half the measurement"


def test_summary_surfaces_the_warnings(doc):
    md = render.summary_md(doc)
    if doc["quality"]["warnings"]:
        assert "What to be careful of" in md


def test_unobserved_values_are_marked_in_the_summary(synthetic_room, tmp_path):
    """A plan with a number on every wall looks equally authoritative whether the ceiling was
    measured or guessed. The difference only exists if the page says so."""
    d = pipeline.run(synthetic_room["path"], stride=2)
    d["rooms"][0]["ceiling_height_m"]["observed"] = False
    assert "not seen" in render.summary_md(d)


def test_report_survives_a_document_with_no_rooms(tmp_path):
    from scanplan.measure import from_sigma
    empty = {
        "schema_version": "0.1.0", "units": "m",
        "capture": {"id": "empty", "tier": "lidar", "pipeline_version": "0.1.0",
                    "runtime_s": 0.1, "drift_correction": False},
        "rooms": [], "plan": {"footprint_m2": from_sigma(0.0, 0.0).as_dict(), "adjacency": []},
        "damage": [], "concealed_flags": [], "scope": [],
        "quality": {"warnings": [{"code": "X", "severity": "error", "message": "nothing found"}]},
    }
    written = render.write_all(empty, tmp_path)
    assert "report.pdf" in written
