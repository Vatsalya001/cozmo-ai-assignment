"""G-CEIL against laser truth, and the three conventions that had to be right.

This project reported G-CEIL as NOT MEASURED twice, with reasons, and both times the reasons
were wrong in the same way: the data was there and the geometry was being read incorrectly.

- `bench/arkitscenes_laser.py` blamed multi-storey venues.
- `bench/ceiling_vs_laser.py` blamed the upsampling split for publishing too few frames.

The actual blockers were three format facts: the ARKitScenes trajectory is **cam_from_world**
and must be inverted, its translation is therefore in the camera frame, and its world is
**z-up** where this project is y-up. With those fixed the same machinery measures 5 of 5 walks
within 15 mm.

The lesson these tests exist to protect is narrow: a NOT MEASURED with a confident explanation
is still a claim, and this project published two that were false. So the tests assert the
measurement holds *and* that the ablation showing why the correction is needed is kept beside
it, because the pair is what makes the result checkable rather than assertable.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "bench" / "results"
CORRECTED = RESULTS / "ceiling_walks.json"
UNCORRECTED = RESULTS / "ceiling_walks_uncorrected.json"


@pytest.fixture(scope="module")
def corrected():
    assert CORRECTED.is_file(), "run bench/ceiling_walks.py"
    return json.loads(CORRECTED.read_text())


@pytest.fixture(scope="module")
def uncorrected():
    assert UNCORRECTED.is_file(), "run bench/ceiling_walks.py --no-bias-correction"
    return json.loads(UNCORRECTED.read_text())


def test_ceiling_height_is_within_the_gate_on_every_scored_walk(corrected):
    """The headline: 1.5 cm per room, against FARO-derived laser depth."""
    assert corrected["walks_scored"] >= 4, "a gate on fewer than four walks is thin evidence"
    assert corrected["gate_met"] is True
    assert corrected["within_gate"] == corrected["total"]
    assert corrected["max_abs_error_mm"] <= 15.0


def test_the_bias_correction_is_held_out_not_fitted(corrected):
    """Correcting a walk with an offset measured on that same walk would absorb the error being
    reported. The offset must come from the other venue."""
    assert corrected["bias_correction"] == "leave-one-venue-out"
    scored = [r for r in corrected["rows"] if "ceiling_error_mm" in r]
    assert scored
    for r in scored:
        assert r["applied_offset_mm"] != 0.0, "a scored walk must carry a correction"


def test_the_ablation_shows_the_correction_is_what_moves_the_gate(corrected, uncorrected):
    """Without this pair the 5/5 is an assertion. With it, the correction's effect is a
    measurement: uncorrected the same walks fail, and by roughly the device bias."""
    assert uncorrected["bias_correction"] == "none"
    assert uncorrected["gate_met"] is False, (
        "if the gate passes with no correction at all, the correction is not what is doing the "
        "work and the error budget is describing something else")
    assert abs(uncorrected["mean_error_mm"]) > abs(corrected["mean_error_mm"]) + 5.0


def test_the_answer_to_biased_or_unrepeatable_is_in_the_data(corrected, uncorrected):
    """G-CEIL-SPREAD requires the report to say whether we are biased or unrepeatable; the brief
    says both fail. The ablation answers it: uncorrected is repeatable and biased, and the
    correction trades the bias for a little repeatability."""
    un_spread = max(uncorrected["spread_within_venue_mm"].values())
    co_spread = max(corrected["spread_within_venue_mm"].values())
    assert abs(uncorrected["mean_error_mm"]) > 15.0, "uncorrected should be clearly biased"
    assert un_spread < co_spread, (
        "the recorded finding is that correcting removes bias at some cost in spread; if that "
        "has reversed, the report's explanation needs revisiting")


def test_the_device_bias_measured_here_agrees_with_the_per_pixel_benchmark(corrected):
    """Two independent measurements of the same physical property, on different scans and by
    different methods: per-pixel over the upsampling split, and near-range on these walks.
    They should agree in sign and rough size, or one of them is measuring something else."""
    disp = np.array(list(corrected["per_walk_disparity_mm"].values()))
    assert len(disp) >= 4
    assert (disp < 0).all(), "every walk should read SHORT of laser truth"
    pooled = json.loads((RESULTS / "depth_bias.json").read_text())["pooled_median_mm"]
    assert pooled < 0
    # Different ranges and methods, so agreement is in sign and order, not to the millimetre.
    assert abs(np.median(disp) - pooled) < 12.0, (
        f"near-range walk disparity median {np.median(disp):.1f} mm vs per-pixel pooled "
        f"{pooled:.1f} mm; a gap this large means the two benchmarks disagree about the sensor")


def test_both_depth_streams_go_through_our_own_fitting(corrected):
    """The laser side is not Apple's annotation. That is what makes this a measurement of our
    geometry rather than a revalidation of the laser, and the caveat must say so."""
    assert "our" in corrected["caveat"] and "annotations" in corrected["caveat"]
    scored = [r for r in corrected["rows"] if "ceiling_error_mm" in r]
    for r in scored:
        assert "ceiling_height_m" in r["device"] and "ceiling_height_m" in r["laser"]


def test_a_walk_that_fails_is_recorded_rather_than_dropped(corrected):
    """One walk produced no floor+ceiling pair from the device stream. Scoring only the walks
    that worked, without saying how many did not, would inflate the result."""
    assert "walks_rejected" in corrected
    assert corrected["walks_scored"] + corrected["walks_rejected"] == len(corrected["rows"])
    for r in corrected["rows"]:
        assert "ceiling_error_mm" in r or "rejected" in r


def test_the_source_of_the_approach_is_credited(corrected):
    """The slice of the dataset that carries this truth was learned from another submission.
    Presenting it as independently found would be dishonest, and the credit costs nothing."""
    assert "independent submission to the same brief" in corrected["credit"]
    assert "Learned from" in corrected["credit"]
