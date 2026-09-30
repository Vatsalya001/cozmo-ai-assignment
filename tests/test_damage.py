"""Damage detection, both directions.

A detector that never fires scores zero false positives and is worthless. A detector that
fires everywhere finds all the damage and is worthless too. Both directions are tested here:
a synthetic wall carrying a defect of known size must be found with roughly the right extent,
and a synthetic flat wall must yield nothing.
"""
from __future__ import annotations

import numpy as np
import pytest

from scanplan.damage import detect as dmg
from scanplan.damage import rules as dmg_rules
from scanplan.geometry.rooms import Room
from scanplan.ir import CaptureIR


def _wall_cloud(bulge=None, *, width=4.0, height=2.5, spacing=0.02):
    """A flat wall at z = 0 spanning x in [0, width], optionally with a bulge.

    `bulge` is (x0, x1, y0, y1, depth_m): the patch stands proud of the wall by depth_m.
    """
    xs = np.arange(0.0, width, spacing)
    ys = np.arange(0.05, height, spacing)
    X, Y = np.meshgrid(xs, ys)
    Z = np.zeros_like(X)
    if bulge:
        x0, x1, y0, y1, d = bulge
        patch = (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
        Z[patch] = d
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    # A closed room polygon whose first wall lies along z = 0.
    poly = np.array([[0.0, 0.0], [width, 0.0], [width, 3.0], [0.0, 3.0]])
    room = Room(id=1, polygon_xz=poly, area_m2=width * 3.0)
    ir = CaptureIR(capture_id="synthetic_wall", tier="lidar")
    ir.points = pts
    return ir, [room]


def test_flat_wall_reports_no_damage():
    ir, rooms = _wall_cloud()
    assert dmg.detect(ir, rooms, floor_y=0.0) == []


def test_a_known_bulge_is_found_with_roughly_the_right_extent():
    """A 40 x 30 cm patch lifted 25 mm -- the scale of blistered plaster."""
    ir, rooms = _wall_cloud(bulge=(1.00, 1.40, 1.00, 1.30, 0.025))
    regions = dmg.detect(ir, rooms, floor_y=0.0)
    assert regions, "a 25 mm bulge over 0.12 m2 must be detected"
    r = max(regions, key=lambda x: x.area_m2)
    assert r.width_m == pytest.approx(0.40, abs=0.12)
    assert r.height_m == pytest.approx(0.30, abs=0.12)
    assert r.height_above_floor_m == pytest.approx(1.00, abs=0.15)


def test_furniture_depth_is_not_reported_as_damage():
    """A wardrobe stands 40 cm off the wall. Blistered plaster lifts by millimetres, so depth
    is what separates them -- without this the detector reports every sofa in the property."""
    ir, rooms = _wall_cloud(bulge=(1.0, 1.8, 0.2, 2.0, 0.40))
    assert dmg.detect(ir, rooms, floor_y=0.0) == []


def test_noise_below_threshold_is_not_damage():
    ir, rooms = _wall_cloud(bulge=(1.0, 1.4, 1.0, 1.3, 0.004))
    assert dmg.detect(ir, rooms, floor_y=0.0) == []


def test_class_is_marked_as_coming_from_shape():
    """Shape cannot name a defect. Reporting a shape-derived class as a visual identification
    would be exactly the confident garbage the brief penalises."""
    ir, rooms = _wall_cloud(bulge=(1.0, 1.4, 1.0, 1.3, 0.025))
    r = dmg.detect(ir, rooms, floor_y=0.0)[0]
    assert r.class_source == "shape"
    assert r.class_confidence <= 0.5, "a shape-only class must not claim high confidence"


# ---- rules and scope -------------------------------------------------------------------

def _region(**kw):
    base = dict(id="D1", surface_id="R1.W1", damage_class="peeling_paint", class_source="shape",
                class_confidence=0.4, width_m=0.4, height_m=0.3, area_m2=0.12,
                height_above_floor_m=1.0, mean_protrusion_m=0.02, max_protrusion_m=0.025)
    base.update(kw)
    return dmg.DamageRegion(**base)


def test_low_damage_fires_the_rising_damp_rule():
    flags = dmg_rules.evaluate([_region(height_above_floor_m=0.10)], [], [], 2.5)
    assert any(f.rule_id == "R1-RISING-DAMP" for f in flags)


def test_high_damage_fires_the_ceiling_leak_rule():
    flags = dmg_rules.evaluate([_region(height_above_floor_m=2.30, height_m=0.15)], [], [], 2.5)
    assert any(f.rule_id == "R2-CEILING-LEAK" for f in flags)


def test_two_regions_on_one_wall_fire_the_shared_surface_rule():
    flags = dmg_rules.evaluate([_region(id="D1"), _region(id="D2")], [], [], 2.5)
    assert any(f.rule_id == "R5-SHARED-SURFACE" for f in flags)


def test_every_flag_names_a_rule_that_exists():
    """A-FLAG: the brief requires the rule that fired, so a flag citing an undocumented rule
    is worse than no flag."""
    flags = dmg_rules.evaluate([_region(height_above_floor_m=0.05, area_m2=0.8,
                                        max_protrusion_m=0.05)], [], [], 2.5)
    assert flags
    for f in flags:
        assert f.rule_id in dmg_rules.RULES


def test_scope_items_key_to_a_surface_and_a_cause():
    """A-SCOPE: every item must point at a real surface and a real reason."""
    regions = [_region()]
    flags = dmg_rules.evaluate(regions, [], [], 2.5)
    items = dmg_rules.scope(regions, flags)
    assert items
    ids = {r.id for r in regions} | {f.rule_id for f in flags}
    for item in items:
        assert item["surface_id"] == "R1.W1"
        assert item["because"] in ids
        assert item["quantity"]["ci_low"] <= item["quantity"]["value"] <= item["quantity"]["ci_high"]


def test_no_damage_means_no_flags_and_no_scope():
    assert dmg_rules.evaluate([], [], [], 2.5) == []
    assert dmg_rules.scope([], []) == []
