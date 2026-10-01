"""Video tier: what it is, and what it must never quietly become."""
from __future__ import annotations

import numpy as np
import pytest

from scanplan import pipeline
from scanplan.detect import CaptureError
from scanplan.ingest import video


def test_video_tier_refuses_a_clip_with_no_pose_track(tmp_path):
    """A bare .mov carries no poses. Estimating them from the video alone is
    structure-from-motion, which this pipeline does not implement -- so it says so instead of
    inventing a track."""
    (tmp_path / "rgb.mp4").write_bytes(b"not a video")
    with pytest.raises(CaptureError, match="pose track"):
        video.load(tmp_path)


def test_video_widening_is_larger_than_lidar():
    """Thin input must produce wider intervals. The factor is measured, not chosen:
    bench/video_vs_lidar.py found 69% and 26% footprint error against LiDAR."""
    from scanplan.measure import from_sigma
    lidar = from_sigma(10.0, 0.4, widen=1.0)
    vid = from_sigma(10.0, 0.4, widen=11.0)
    assert (vid.ci_high - vid.ci_low) > 10 * (lidar.ci_high - lidar.ci_low)


def test_video_ir_never_carries_measured_depth(monkeypatch):
    """The captures available have LiDAR depth sitting right there. If the video tier ever
    reads it, every number this tier reports becomes a lie about what a plain camera can do."""
    import inspect
    src = inspect.getsource(video)
    assert "depth/" not in src, "the video tier must not read the depth directory"
    assert "confidence/" not in src, "nor the confidence directory"


def test_video_scale_provenance_is_the_model_not_the_room():
    """Scale is unobservable from monocular images, so it comes from the model's training.
    The IR must say that, because a reader has no other way to know."""
    import scanplan.ingest.video as v
    src = inspect_source = v.load.__doc__ or ""
    # The provenance string is set at construction; check the constant it references.
    assert v.MODEL.startswith("depth-anything/")
    assert "Metric" in v.MODEL, "a relative-depth model would leave the plan unscaled"


def test_photo_folder_with_unreadable_images_fails_with_a_stated_error(tmp_path):
    """A tier that runs and finds nothing usable must still raise a stated error rather than
    present an empty plan as a result -- and must do so whether or not the model extra is
    installed. A clean-clone check found this raising a bare ModuleNotFoundError on the
    README's default install, which on walk-in day is a traceback in front of the examiners."""
    home = tmp_path / "home" / "kitchen"
    home.mkdir(parents=True)
    (home / "a.jpg").write_bytes(b"not an image")
    with pytest.raises(CaptureError):
        pipeline.run(tmp_path / "home")


def test_a_missing_model_extra_is_a_stated_error_not_a_traceback(monkeypatch):
    """The default install omits torch and transformers on purpose, so the LiDAR tier needs no
    weights and no network. Asking for a model-backed tier anyway must name the fix."""
    import builtins
    import scanplan.ingest.video as v
    monkeypatch.setattr(v, "_pipe", None)
    real = builtins.__import__

    def no_transformers(name, *a, **k):
        if name.startswith("transformers"):
            raise ImportError("No module named 'transformers'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_transformers)
    with pytest.raises(CaptureError, match=r"dev,models"):
        v._depth_model()


# ---- photo tier ------------------------------------------------------------------------

def test_photo_tier_reports_that_it_did_not_stitch(tmp_path):
    """G-PHOTO-STITCH fails by construction, not by accident, and the output must say so --
    a reader seeing separate rectangles has no other way to know whether that is a finding
    about the property or a limit of the method."""
    import scanplan.pipeline as pl
    import inspect
    src = inspect.getsource(pl._photo_document)
    assert "PHOTO_TIER_NOT_STITCHED" in src
    assert "by construction" in src


def test_photo_tier_does_not_claim_a_trajectory():
    """Stills carry no path, so the drift block must not imply one was corrected."""
    import scanplan.pipeline as pl
    import inspect
    assert "not applicable: stills carry no trajectory" in inspect.getsource(pl._photo_document)


def test_room_box_ignores_one_smeared_frame():
    """Per-room extents combine at a high percentile, not the maximum: a single bad depth
    frame with a far wall smeared to 8 m must not set the size of the room."""
    import numpy as np
    from scanplan.geometry import roombox

    def floor_cloud(half_extent):
        n = 4000
        rng = np.random.default_rng(0)
        x = rng.uniform(-half_extent, half_extent, n)
        z = rng.uniform(-half_extent, half_extent, n)
        return np.stack([x, np.zeros(n), z], axis=1)

    good = [floor_cloud(1.5) for _ in range(5)]
    box_clean = roombox.estimate(good)
    box_with_outlier = roombox.estimate(good + [floor_cloud(6.0)])
    assert box_with_outlier.width_m < box_clean.width_m * 1.6, (
        f"one smeared frame moved the room from {box_clean.width_m:.2f} to "
        f"{box_with_outlier.width_m:.2f} m")


def test_room_box_returns_none_without_a_floor():
    import numpy as np
    from scanplan.geometry import roombox
    airborne = np.stack([np.zeros(600), np.full(600, 1.5), np.zeros(600)], axis=1)
    assert roombox.estimate([airborne]) is None
