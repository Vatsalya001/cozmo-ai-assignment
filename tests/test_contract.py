"""The output contract, the validator, and the failure modes that must not reach a demo.

The brief's walk-in test is a cold run in front of the examiners, so "does it refuse
gracefully" is worth as much here as "does it compute correctly".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scanplan import detect, measure, pipeline, validate

ROOT = Path(__file__).resolve().parents[1]


# ---- intervals ----------------------------------------------------------------------

def test_interval_brackets_its_value():
    m = measure.from_sigma(3.5, 0.02)
    assert m.ci_low < m.value < m.ci_high
    assert m.contains(3.5)


def test_widening_factor_widens():
    narrow = measure.from_sigma(3.5, 0.02, widen=1.0)
    wide = measure.from_sigma(3.5, 0.02, widen=4.5)
    assert (wide.ci_high - wide.ci_low) > 4 * (narrow.ci_high - narrow.ci_low)


def test_log_scale_interval_never_goes_negative():
    """Thin input needs wide intervals, and a wide symmetric interval on a small value goes
    below zero, which is not a length anything can have."""
    m = measure.log_scale(0.30, 3.0)
    assert m.ci_low > 0


def test_unobserved_is_flagged_not_hidden():
    m = measure.unobserved(2.55, 1.25)
    assert m.observed is False
    assert not m.as_dict().get("observed", True)


def test_coverage_counts_what_it_should():
    ms = [measure.from_sigma(1.0, 0.1), measure.from_sigma(2.0, 0.1)]
    assert measure.coverage(ms, [1.0, 5.0]) == pytest.approx(0.5)


# ---- validator ----------------------------------------------------------------------

def _minimal_doc():
    return {
        "schema_version": "0.1.0", "units": "m",
        "capture": {"id": "t", "tier": "lidar", "pipeline_version": "0.1.0"},
        "rooms": [], "plan": {"footprint_m2": measure.from_sigma(10.0, 0.4).as_dict(),
                              "adjacency": []},
        "damage": [], "concealed_flags": [], "scope": [],
        "quality": {"warnings": []},
    }


def test_minimal_document_is_valid():
    assert validate.validate(_minimal_doc()) == []


def test_validator_rejects_an_inverted_interval():
    """JSON Schema cannot express ci_low <= value <= ci_high across sibling keys, so this is
    checked separately. It has already caught one real bug."""
    doc = _minimal_doc()
    doc["plan"]["footprint_m2"] = {"value": 10.0, "ci_low": 12.0, "ci_high": 9.0,
                                   "confidence": 0.9}
    problems = validate.validate(doc)
    assert any("ci_low" in p for p in problems)


def test_validator_rejects_a_missing_section():
    doc = _minimal_doc()
    del doc["quality"]
    assert validate.validate(doc)


def test_scope_must_reference_something_real():
    """The brief requires scope keyed to surfaces and flags naming the rule that fired."""
    doc = _minimal_doc()
    doc["scope"] = [{"id": "S1", "surface_id": "nope", "item": "paint", "unit": "m2",
                     "quantity": measure.from_sigma(4.0, 0.2).as_dict(), "because": "ghost"}]
    assert any("because" in p or "surface" in p for p in validate.validate(doc))


# ---- tier detection and graceful failure --------------------------------------------

def test_detects_the_lidar_tier(synthetic_room):
    assert detect.detect_tier(synthetic_room["path"]) == "lidar"


def test_detects_video_and_photo_tiers(tmp_path):
    (tmp_path / "walk.mov").write_bytes(b"")
    assert detect.detect_tier(tmp_path / "walk.mov") == "video"
    home = tmp_path / "home"
    (home / "kitchen").mkdir(parents=True)
    (home / "kitchen" / "a.jpg").write_bytes(b"")
    assert detect.detect_tier(home) == "photo"


def test_missing_path_is_a_clean_error(tmp_path):
    with pytest.raises(detect.CaptureError):
        detect.detect_tier(tmp_path / "nothing")


def test_loose_photos_explain_the_expected_layout(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"")
    with pytest.raises(detect.CaptureError, match="one folder per room"):
        detect.detect_tier(tmp_path)


def test_cli_never_shows_a_traceback(tmp_path):
    """A traceback in front of the examiners is worth less than a stated failure."""
    r = subprocess.run([sys.executable, "-m", "scanplan.cli", "run", str(tmp_path / "absent")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    assert "error:" in r.stderr


# ---- end to end ----------------------------------------------------------------------

def test_pipeline_output_validates(synthetic_room):
    doc = pipeline.run(synthetic_room["path"], stride=2)
    assert validate.validate(doc) == [], "the pipeline must never emit an invalid document"
    assert doc["rooms"]
    assert doc["capture"]["tier"] == "lidar"


def test_every_measurement_has_an_interval(synthetic_room):
    doc = pipeline.run(synthetic_room["path"], stride=2)
    seen = 0

    def walk(node):
        nonlocal seen
        if isinstance(node, dict):
            if "value" in node and "ci_low" in node:
                seen += 1
                assert node["ci_low"] <= node["value"] <= node["ci_high"]
                assert node["confidence"] == 0.9
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    assert seen >= 5, "the contract requires an interval on every measurement"


def test_pipeline_is_deterministic(synthetic_room):
    """A-DET, and a precondition for a regenerable fix loop."""
    a = pipeline.run(synthetic_room["path"], stride=2)
    b = pipeline.run(synthetic_room["path"], stride=2)
    for d in (a, b):
        d["capture"].pop("runtime_s")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
