"""Every tuned constant must be derivable from a committed measurement.

A constant in the source that cites a benchmark is a claim: "this number came from that
experiment." Nothing enforced the claim, and it had already broken once. `RESIDUAL_DEPTH_BIAS_M`
was set to 4 mm citing bench/depth_bias.py, but that benchmark published only the *range* of the
per-scan medians, 13 mm. The 4 mm standard deviation appeared in no committed file, so a
reviewer who opened depth_bias.json to check the constant would find 13 and reasonably conclude
the number had been invented. The constant was right; it was simply unverifiable.

These tests close that gap by reading the committed JSON and re-deriving each constant from it.
If a benchmark is re-run on more scans and the measurement moves, these fail and the constants
must be updated deliberately rather than drifting apart in silence.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

RESULTS = Path(__file__).resolve().parents[1] / "bench" / "results"


@pytest.fixture(scope="module")
def bias():
    path = RESULTS / "depth_bias.json"
    assert path.is_file(), (
        "bench/results/depth_bias.json is committed on purpose: the depth-bias correction is "
        "the one sensor constant measured against laser truth, and the measurement travels "
        "with the code that depends on it")
    return json.loads(path.read_text())


def test_the_correction_applied_at_ingest_is_the_measured_pooled_median(bias):
    """The loader adds back exactly what the device was measured to read short by. A correction
    that drifted from its measurement would be a tuning knob wearing a measurement's name."""
    from scanplan.ingest import stray
    measured_short_by_m = -bias["pooled_median_mm"] / 1000.0
    assert stray.DEPTH_BIAS_CORRECTION_M == pytest.approx(measured_short_by_m, abs=5e-4), (
        f"ingest corrects by {stray.DEPTH_BIAS_CORRECTION_M*1000:.1f} mm but the measurement "
        f"says the device reads {measured_short_by_m*1000:.1f} mm short")


def test_the_residual_in_every_interval_is_the_measured_scan_to_scan_deviation(bias):
    """One correction cannot fit eight scans. What it leaves unexplained is carried on every
    surface height, and it must be the deviation actually measured -- not the range, which is
    three times larger, and not a round number chosen to look careful."""
    from scanplan.geometry import planes
    assert planes.RESIDUAL_DEPTH_BIAS_M == pytest.approx(
        bias["std_across_scans_mm"] / 1000.0, abs=5e-4)


def test_the_published_summaries_are_what_they_claim_to_be(bias):
    """Guards the specific confusion that caused this file to exist: two different summaries of
    the same eight numbers, published under names that must not be swapped."""
    medians = np.array([s["median_bias_mm"] for s in bias["scans"]])
    assert len(medians) >= 2, "a spread over fewer than two scans is not a spread"
    assert bias["range_across_scans_mm"] == pytest.approx(medians.max() - medians.min(), abs=1e-6)
    assert bias["std_across_scans_mm"] == pytest.approx(medians.std(ddof=1), abs=1e-6)
    assert bias["range_across_scans_mm"] > bias["std_across_scans_mm"], (
        "the range must exceed the deviation; if these are equal the two fields are the same "
        "quantity under two names and the distinction this file exists to protect is gone")


def test_the_device_reads_short_not_long(bias):
    """The sign is the part that silently doubles the error if it is wrong: correcting the
    wrong way turns an 18 mm bias into a 36 mm one, and every surface would still look fitted."""
    assert bias["sign_convention"].startswith("positive means the device reads LONGER")
    assert bias["pooled_median_mm"] < 0, "a negative pooled median is what 'reads short' means"

    from scanplan.ingest import stray
    assert stray.DEPTH_BIAS_CORRECTION_M > 0, "reading short means the correction must ADD depth"


def test_the_measurement_rests_on_enough_pixels_to_mean_anything(bias):
    """Stated in the report as 4.79 million pixels across 8 scans. If a future run narrows the
    input, the headline claim stops being true and this says so."""
    assert bias["total_pixels"] >= 1_000_000
    assert len(bias["scans"]) >= 4
    assert sum(s["pixels"] for s in bias["scans"]) == pytest.approx(bias["total_pixels"], rel=0.02)
