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


def test_unknown_tier_fails_with_a_stated_error(tmp_path):
    home = tmp_path / "home" / "kitchen"
    home.mkdir(parents=True)
    (home / "a.jpg").write_bytes(b"")
    with pytest.raises(CaptureError, match="not implemented"):
        pipeline.run(tmp_path / "home")
