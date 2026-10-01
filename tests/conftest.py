"""Fixtures over the synthetic capture generator.

The generator itself is `scanplan/synthetic.py` -- it lives in the package because
`bench/head_to_head_engineer.py` needs it, and a benchmark importing from the test suite is the
wrong direction. Its docstring explains what the fixture models and the two bugs that shaped it.
"""
from __future__ import annotations

import pytest

from scanplan.synthetic import (                      # noqa: F401 -- re-exported for tests
    CAMERA_HEIGHT_M,
    DEFAULT_FRAMES,
    DEPTH_H,
    DEPTH_W,
    DEVICE_BIAS_M,
    depth_intrinsics,
    write_stray_capture,
)


@pytest.fixture(scope="session")
def synthetic_room(tmp_path_factory):
    """A 4.00 x 3.00 m room, 2.50 m ceiling. Built once; the tests only read it."""
    return write_stray_capture(tmp_path_factory.mktemp("synthetic") / "box_room")


@pytest.fixture(scope="session")
def synthetic_ir(synthetic_room):
    """The fused cloud at stride 1.

    Stride 1 is deliberate: these fixtures feed the tests that check geometry *functions* in
    isolation, where more points is simply a better test. The product's own default stride is 3,
    and `test_the_product_can_process_the_capture_we_generate` covers that path separately --
    the gap between the two is where a real bug hid.
    """
    from scanplan.geometry import fusion
    from scanplan.ingest import stray
    ir = stray.load(synthetic_room["path"], stride=1)
    fusion.fuse(ir)
    return ir
