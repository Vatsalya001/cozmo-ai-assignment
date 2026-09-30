"""One capture in, one contract document out.

Every tier converges here: a tier-specific loader fills a CaptureIR, and from that point the
geometry, the error model and the output are identical. That is the whole reason the IR
exists -- three tiers cannot otherwise be built, benchmarked and defended in the time
available, and the brief requires the same output contract from each.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import cv2
import numpy as np

from . import __version__
from .detect import CaptureError, detect_tier
from .geometry import fusion, planes, regularize, rooms as rooms_mod, walls
from .ir import CaptureIR
from . import quality
from .damage import detect as damage_detect, rules as damage_rules
from .slam import drift as drift_mod
from .measure import Measurement, from_sigma, log_scale, unobserved

# One-sigma on a wall length, from the supplied captures: 2 cm depth noise at the surface
# plus the residual of the plane fit. Replaced by a measured value once the ARKitScenes
# laser comparison runs.
WALL_SIGMA_M = 0.025
AREA_RELATIVE_SIGMA = 0.04
OPENING_SIGMA_M = 0.04
TYPICAL_DOOR_M = 0.80


def _room_document(room: rooms_mod.Room, storey: tuple[float, float] | None,
                   openings: list[rooms_mod.Opening], widen: float) -> dict:
    lengths = room.wall_lengths()
    poly = room.polygon_xz

    if storey is None:
        ceiling = unobserved(2.55, 1.25, method="not seen; population typical")
    else:
        ceiling = from_sigma(storey[0], storey[1], widen=widen,
                             method="ceiling plane minus floor plane")

    walls_out = []
    for i, L in enumerate(lengths, 1):
        a, b = poly[i - 1], poly[i % len(poly)]
        walls_out.append({
            "id": f"R{room.id}.W{i}",
            "surface_id": f"R{room.id}.W{i}",
            "start": [round(float(a[0]), 3), round(float(a[1]), 3)],
            "end": [round(float(b[0]), 3), round(float(b[1]), 3)],
            "length_m": from_sigma(L, WALL_SIGMA_M, widen=widen,
                                   method="corner to corner, inside faces").as_dict(),
        })

    ops_out = []
    for op in openings:
        if room.id not in op.rooms:
            continue
        other = op.rooms[0] if op.rooms[1] == room.id else op.rooms[1]
        ops_out.append({
            "id": f"R{room.id}.{op.id}",
            "kind": "door" if op.width_m < 1.1 else "gap",
            "wall_id": f"R{room.id}.W1",
            "width_m": from_sigma(op.width_m, OPENING_SIGMA_M, widen=widen,
                                  method="clear width at the narrowest point").as_dict(),
            "connects_to": f"R{other}",
        })

    return {
        "id": f"R{room.id}",
        "label": f"room {room.id}",
        "polygon": [[round(float(x), 3), round(float(z), 3)] for x, z in poly],
        "floor_area_m2": from_sigma(room.area_m2, room.area_m2 * AREA_RELATIVE_SIGMA,
                                    widen=widen, method="measured floor coverage").as_dict(),
        "perimeter_m": from_sigma(room.perimeter_m, WALL_SIGMA_M * math.sqrt(len(lengths)),
                                  widen=widen, method="sum of wall lengths").as_dict(),
        "ceiling_height_m": ceiling.as_dict(),
        "walls": walls_out,
        "openings": ops_out,
    }


def run(path, *, tier: str | None = None, stride: int = 3, drift: bool = True,
        damage: bool = True, door_max_m: float | None = None,
        min_seed_area_m2: float | None = None) -> dict:
    """Measure a capture and return a document that satisfies schema/output.schema.json.

    The two room-split tunables are explicit parameters rather than module constants read at
    call time. Patching the constants does not work: Python binds a default argument once, at
    definition, so `rooms_mod.DOOR_MAX_M = 0.70` silently changes nothing while
    `MIN_SEED_AREA_M2`, read inside the function body, does change. An ablation built on that
    mixture reported a 'before' that was half the fix, which is how a fix loop ends up
    confidently measuring the wrong thing.
    """
    started = time.perf_counter()
    source = Path(path)
    tier = tier or detect_tier(source)

    if tier == "lidar":
        from .ingest import stray
        ir: CaptureIR = stray.load(source, stride=stride)
    else:
        raise CaptureError(f"the {tier} tier is not implemented yet")

    drift_report = drift_mod.correct(ir, apply=drift)

    fusion.fuse(ir)
    floor, ceiling = planes.floor_and_ceiling(ir.points, ir.trajectory[:, 1])
    if floor is None:
        raise CaptureError(f"{source}: no floor found; the capture must show the floor")
    storey = planes.ceiling_height(floor, ceiling)

    # Yaw-align before rasterising: the cloud is gravity-aligned but sits at whatever heading
    # the capture began at, so the grid axes would otherwise cut every wall diagonally.
    #
    # The angle must come from the walls themselves. The principal axis of the floor scatter
    # was tried first and is the wrong quantity: it finds the direction the property is
    # longest in, which in an L-shaped flat is a diagonal across the L and matches no wall at
    # all. So the cloud is rasterised once, the wall lines are found, and their dominant
    # direction sets the rotation.
    probe = walls.density(ir.points, floor.height_m)
    orientations = walls.dominant_orientations(walls.wall_mask(probe))
    yaw = orientations[0] if orientations else 0.0
    ir.points = regularize.rotate_about_y(ir.points, yaw)
    for f in ir.frames:
        f.world_from_cam = f.world_from_cam.copy()
        f.world_from_cam[:3, 3] = regularize.rotate_about_y(f.position[None, :], yaw)[0]

    grid = walls.density(ir.points, floor.height_m)
    wall_mask = walls.wall_mask(grid)
    coverage = walls.floor_coverage(ir.points, floor.height_m, grid)
    free = (coverage & ~cv2.dilate(wall_mask, np.ones((3, 3), np.uint8)).astype(bool)).astype(np.uint8)

    split_kw = {}
    if door_max_m is not None:
        split_kw["door_max_m"] = door_max_m
    if min_seed_area_m2 is not None:
        split_kw["min_seed_area_m2"] = min_seed_area_m2
    labels = rooms_mod.split_rooms(free, grid, **split_kw)
    found = rooms_mod.polygons(labels, grid)
    for r in found:
        r.polygon_xz = regularize.rectify(r.polygon_xz)
    openings = rooms_mod.openings(labels, grid, free)

    regions, flags, scope_items = [], [], []
    if damage:
        regions = damage_detect.detect(ir, found, floor.height_m)
        flags = damage_rules.evaluate(regions, found, openings,
                                      storey[0] if storey else None)
        scope_items = damage_rules.scope(regions, flags)

    rgb = source / "rgb.mp4"
    conditions = quality.assess(ir, found, coverage=coverage, grid=grid,
                                video_path=rgb if rgb.is_file() else None)

    widen = {"lidar": 1.0, "video": 4.5, "photo": 5.1}[tier]
    room_docs = [_room_document(r, storey, openings, widen) for r in found]
    footprint = sum(r.area_m2 for r in found)

    warnings = [{"code": "GEOMETRY_WARNING", "severity": "warning", "message": w}
                for w in ir.warnings]
    warnings += conditions.warnings()
    if ceiling is None:
        warnings.append({"code": "NO_CEILING", "severity": "warning",
                         "message": "the ceiling was never seen; ceiling heights are population "
                                    "typicals with wide intervals, flagged observed=false"})
    warnings.append({"code": "ROOM_SPLIT_CONSERVATIVE", "severity": "info",
                     "message": "rooms are split at doorway-width necks and under-split rather "
                                "than over-split; a merged pair still reports a correct combined "
                                "floor area, an invented room does not"})
    if not damage:
        warnings.append({"code": "DAMAGE_OFF", "severity": "info",
                         "message": "damage detection switched off (--no-damage)"})
    elif regions:
        warnings.append({"code": "DAMAGE_CLASS_FROM_SHAPE", "severity": "warning",
                         "message": f"{len(regions)} damage region(s) located geometrically, as "
                                    f"departures from the wall plane. Extents are measured; the "
                                    f"CLASS is inferred from shape alone and is reported with low "
                                    f"confidence. Naming a defect needs appearance, not shape -- a "
                                    f"stain that has not lifted the plaster is perfectly flat"})

    return {
        "schema_version": "0.1.0",
        "units": "m",
        "capture": {
            "id": source.stem or source.name,
            "tier": tier,
            "source_path": str(source),
            "frames": len(ir.frames),
            "pipeline_version": __version__,
            "runtime_s": round(time.perf_counter() - started, 2),
            "drift_correction": bool(drift),
        },
        "rooms": room_docs,
        "plan": {
            "footprint_m2": from_sigma(footprint, footprint * AREA_RELATIVE_SIGMA, widen=widen,
                                       method="sum of room floor areas, inside faces").as_dict(),
            "adjacency": [{"from": f"R{a}", "to": f"R{b}", "via": op.id}
                          for op in openings for a, b in [op.rooms]],
            "groups": 1 if room_docs else 0,
            "overlap_m2": 0.0,
            "drift": drift_report.as_dict(),
        },
        "damage": [r.as_dict() for r in regions],
        "concealed_flags": [f.as_dict() for f in flags],
        "scope": scope_items,
        "quality": {
            "warnings": warnings,
            "scene_conditions": conditions.as_dict(),
            "interval_widening_factor": widen,
        },
    }
