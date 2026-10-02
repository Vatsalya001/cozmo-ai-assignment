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
import re
import sys
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


def test_the_compliance_matrix_gate_table_matches_the_benchmark():
    """The matrix already claimed once to be generated when it was not, and its A-RUNTIME row
    drifted for exactly as long as nobody checked. A false claim of generation is worse than an
    honest hand-written table: it tells the reader not to check the thing that is wrong."""
    import subprocess
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "scripts/sync_compliance_matrix.py", "--check"],
                          cwd=root, capture_output=True, text=True)
    assert done.returncode == 0, (
        f"{done.stdout}{done.stderr}\n"
        f"docs/compliance_matrix.md is out of date with bench/results/gates.json. "
        f"Run: python scripts/sync_compliance_matrix.py")


def test_every_reported_gate_has_a_definition_to_look_up():
    """A failing number with no definition is unauditable. Four IDs were reported with no
    definition anywhere -- including G-REPEAT-FOOTPRINT, one of the gates that fails -- so a
    reader checking the failure had nothing to check it against."""
    import re
    root = Path(__file__).resolve().parents[1]
    gates = json.loads((RESULTS / "gates.json").read_text())
    reported = {r["gate"] for r in gates["rows"]}
    defined = set(re.findall(r"\|\s*\*{0,2}([A-Z]-[A-Z0-9-]+)\*{0,2}\s*\|",
                             (root / "docs" / "gates.md").read_text()))
    missing = sorted(reported - defined)
    assert not missing, (
        f"bench/gates.py reports {missing} but docs/gates.md defines no target for them. "
        f"Every number in the gate table must be checkable against a stated target.")


def test_no_committed_result_carries_an_absolute_path():
    """A machine-specific path in a result makes that file disagree with itself on any other
    machine, for a reason that has nothing to do with the measurement. Both offenders are
    fixed -- photo_tier recorded /tmp/photoset as its source, and video_vs_lidar embedded the
    full capture path inside a CaptureError message -- and this keeps them fixed."""
    offenders = []
    for path in sorted(RESULTS.glob("*.json")):
        text = path.read_text()
        for marker in ("/home/", "/Users/", "C:\\\\", "/tmp/"):
            if marker in text:
                offenders.append(f"{path.name} contains {marker!r}")
    assert not offenders, "\n".join(offenders)


def test_the_capture_protocol_does_not_ask_for_an_input_the_code_rejects():
    """The protocol told reviewers to record the video tier with the stock Camera app, while
    `scanplan/ingest/video.py` raises CaptureError on a bare clip because the tier needs the
    phone's pose track. A one-page protocol that produces an unusable capture is worse than no
    protocol: the reviewer follows it, the run fails, and the failure looks like our bug.

    Found when a reviewer with a non-LiDAR iPhone asked what to capture, which is exactly the
    reader the page is written for.
    """
    root = Path(__file__).resolve().parents[1]
    protocol = (root / "docs" / "capture_protocol.md").read_text()
    video_src = (root / "scanplan" / "ingest" / "video.py").read_text()

    # The code's requirement, asserted rather than assumed: if this stops being true the test
    # below is measuring nothing.
    assert "odometry.csv" in video_src, (
        "video.py no longer mentions odometry.csv; re-derive what the video tier needs before "
        "trusting the protocol check below")

    tier2 = protocol.split("## Tier 2")[1].split("## Tier 3")[0]
    assert "odometry.csv" in tier2, (
        "Tier 2 of the protocol must name the file the tier actually needs, or a reviewer "
        "cannot tell a usable capture from an unusable one")
    assert "Camera app" not in tier2 or "not the Camera app" in tier2, (
        "Tier 2 must not send the reviewer to the stock Camera app: a bare .mov carries no "
        "poses and scanplan run refuses it")
    assert "export the walkthrough video as" not in protocol, (
        "the hand-off section must not ask for a camera-roll video export; it drops the pose "
        "track that Tier 2 depends on")


def test_the_photo_tier_warns_when_a_still_is_not_landscape():
    """The tier resizes every still to a fixed 4:3 landscape grid WITHOUT preserving aspect,
    while _intrinsics_from_exif carries one focal length for both axes. That pairing is only
    sound on 4:3 landscape input. cv2.imread applies the EXIF orientation tag, so a photo shot
    in portrait comes back rotated and is then squashed by 1.78x in one direction -- and every
    length derived from it is wrong by that factor, with nothing in the output saying so.

    Found when an operator asked whether to shoot in portrait. The protocol said "upright",
    which reads as portrait and would have produced exactly that silent error.
    """
    root = Path(__file__).resolve().parents[1]
    src = (root / "scanplan" / "ingest" / "photos.py").read_text()
    protocol = (root / "docs" / "capture_protocol.md").read_text()

    assert "aspect_mismatch" in src, (
        "the non-landscape guard is gone; a portrait photo would be stretched silently")
    assert "LANDSCAPE" in src, "the warning must name the fix, not just the symptom"

    tier3 = protocol.split("## Tier 3")[1].split("## What to avoid")[0]
    assert "landscape" in tier3.lower(), (
        "Tier 3 must tell the operator to shoot landscape; 'upright' reads as portrait and is "
        "the input this tier silently distorts")
    assert "upright" not in tier3.lower(), (
        "Tier 3 must not say 'upright' for photos -- that is what sent an operator toward "
        "portrait in the first place")


def test_the_fixed_grid_really_does_distort_portrait_by_the_factor_claimed():
    """The 1.78x in the warning and the protocol is arithmetic, not a guess -- so it is checked
    here rather than trusted, and it fails if DEPTH_W/DEPTH_H ever change without the prose."""
    from scanplan.ingest.photos import DEPTH_H, DEPTH_W
    assert (DEPTH_W, DEPTH_H) == (256, 192), "grid changed; the 1.78x figure must be re-derived"
    for w, h in ((4032, 3024), (1920, 1440)):          # landscape 4:3
        sx, sy = DEPTH_W / w, DEPTH_H / h
        assert abs(max(sx, sy) / min(sx, sy) - 1.0) < 1e-6, "landscape must be isotropic"
    for w, h in ((3024, 4032), (1440, 1920)):          # portrait 3:4
        sx, sy = DEPTH_W / w, DEPTH_H / h
        assert abs(max(sx, sy) / min(sx, sy) - 1.7778) < 1e-3, (
            "portrait anisotropy is not the 1.78x the warning and the protocol both claim")


def test_the_documented_test_count_matches_the_suite():
    """README.md and docs/walk_in.md both print an expected `pytest -q` count. Both said
    "98 passed" while the suite was at 208 -- and docs/walk_in.md is the DEFENCE-DAY runbook,
    so that number would have been read out loud in front of examiners against a terminal
    showing something else.

    Counted by collection rather than by running the suite (which would recurse): a number in a
    document that nothing checks is a number that drifts.
    """
    import subprocess
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                         cwd=root, capture_output=True, text=True, timeout=180).stdout
    m = re.search(r"(\d+)\s+tests? collected", out)
    assert m, f"could not read the collected count from pytest:\n{out[-400:]}"
    collected = int(m.group(1))

    for rel in ("README.md", "docs/walk_in.md"):
        text = (root / rel).read_text()
        found = re.findall(r"pytest -q\s*#\s*(?:expect:\s*)?(\d+)\s+passed", text)
        assert found, f"{rel} no longer documents a pytest count; this guard is measuring nothing"
        for claimed in found:
            assert int(claimed) == collected, (
                f"{rel} says 'pytest -q -> {claimed} passed' but the suite collects "
                f"{collected}. Update the document, not this test.")
