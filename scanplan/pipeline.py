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


def _photo_document(ir, source, started, drift, damage) -> dict:
    """The photo tier's own assembly: a room box per folder, joined to nothing.

    It does not reuse the walked-capture path because that path asks questions -- where is the
    connected floor, where are the necks between rooms -- that a handful of unposed stills
    cannot answer. Running it anyway returns zero rooms, which is the honest answer to the
    wrong question.
    """
    from .geometry import roombox

    widen = 11.0
    rooms_out, origin_x, boxes = [], 0.0, []
    for i, (name, clouds) in enumerate(ir.photo_room_clouds.items(), 1):
        box = roombox.estimate(clouds)
        if box is None:
            continue
        boxes.append((name, box))
        room = roombox.as_room(box, i, origin_x)
        storey = (box.ceiling_m, 0.25) if box.ceiling_m else None
        doc = _room_document(room, storey, [], widen)
        doc["label"] = name
        rooms_out.append(doc)
        origin_x += box.width_m + 2.0

    if not rooms_out:
        raise CaptureError(f"{source}: no room folder produced a usable box")

    footprint = sum(b.area_m2 for _, b in boxes)
    warnings = [{"code": "GEOMETRY_WARNING", "severity": "warning", "message": w}
                for w in ir.warnings]
    warnings.append({
        "code": "PHOTO_TIER_NOT_STITCHED", "severity": "error",
        "message": f"{len(rooms_out)} room(s) are reported as separate rectangles, laid out side "
                   f"by side and joined to nothing. With no camera poses there is nothing in the "
                   f"input that says how the rooms relate, so the whole-property stitch gate "
                   f"fails by construction rather than by accident. Each room is the bounding "
                   f"box of what one view could see: an L-shaped room returns as a rectangle"})

    return {
        "schema_version": "0.1.0", "units": "m",
        "capture": {"id": source.stem or source.name, "tier": "photo",
                    "source_path": str(source), "frames": len(ir.frames),
                    "pipeline_version": __version__,
                    "runtime_s": round(time.perf_counter() - started, 2),
                    "drift_correction": False},
        "rooms": rooms_out,
        "plan": {
            "footprint_m2": from_sigma(footprint, footprint * AREA_RELATIVE_SIGMA, widen=widen,
                                       method="sum of per-room boxes from unposed views").as_dict(),
            "adjacency": [],
            "groups": len(rooms_out),
            "overlap_m2": 0.0,
            "drift": {"method": "not applicable: stills carry no trajectory",
                      "loop_closures": 0, "applied": False},
        },
        "damage": [], "concealed_flags": [], "scope": [],
        "quality": {"warnings": warnings,
                    "scene_conditions": {"mirror": False, "glass": False,
                                         "wet_floor": False, "low_light": False},
                    "interval_widening_factor": widen},
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
    elif tier == "video":
        from .ingest import video
        ir = video.load(source)
    elif tier == "photo":
        from .ingest import photos
        ir = photos.load(source)
    else:
        raise CaptureError(f"the {tier} tier is not implemented yet")

    drift_report = drift_mod.correct(ir, apply=drift)

    if tier == "photo":
        return _photo_document(ir, source, started, drift, damage)

    fusion.fuse(ir, min_confidence=0 if tier == 'video' else 1)
    floor, ceiling = planes.floor_and_ceiling(ir.points, ir.trajectory[:, 1])
    if floor is None:
        # Distinguish two very different causes that used to give the same message.
        #
        # If nothing at all is below the camera, the frames we KEPT never looked down -- which
        # does not mean the capture never looked down. A capture whose sweep is periodic can
        # alias with a fixed stride: one real export cycles its pitch every 3 frames, and
        # stride 3 then samples the same upward pitch forever. Telling the operator "the
        # capture must show the floor" when it plainly does, and offering no way to change the
        # sampling, is the worst of both.
        below = (ir.points[:, 1] < float(np.median(ir.trajectory[:, 1]))).sum()
        if below == 0 and stride > 1:
            raise CaptureError(
                f"{source}: no floor found, and none of the {len(ir.frames)} sampled frames "
                f"looked below the camera at all. That is the signature of a periodic capture "
                f"sweep aliasing with the frame stride rather than of a capture that never saw "
                f"the floor. Re-run with --stride 1 (slower, keeps every frame); if that also "
                f"finds no floor, the capture genuinely never showed it")
        # Say which of the two it is rather than asserting "too few". On the video tier of
        # c7d28f72c6 this branch reports 56% of points below the camera -- not too few by any
        # reading -- so the old wording named the wrong cause. Plenty of points below the
        # camera with no floor among them means no single height holds enough of them to be a
        # surface, which is what inferred depth looks like when it is inconsistent frame to
        # frame. A diagnostic that misnames the cause is worse than one that just gives numbers.
        share = below / max(len(ir.points), 1)
        if share < 0.05:
            why = (f"only {share*100:.1f}% of points are below the camera, so the floor was "
                   f"barely seen -- ask for a re-walk with the floor sweep in "
                   f"docs/capture_protocol.md")
        else:
            why = (f"{share*100:.0f}% of points ARE below the camera, but no single height "
                   f"holds enough of them to be a surface. That is what depth looks like when "
                   f"it is inconsistent between frames rather than when the floor was unseen, "
                   f"and on the video tier it is the inferred depth rather than the capture")
        raise CaptureError(
            f"{source}: no floor found. {below} of {len(ir.points)} points below the camera: "
            f"{why}")
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

    # Measured, not inherited. bench/video_vs_lidar.py put the video tier 69% and 26% away
    # from the LiDAR result on the same captures, and x4.5 left the reference outside the
    # interval on both. x11 is the factor that would have contained them. An interval that
    # excludes the reference is worse than no interval: it claims a precision never present.
    widen = {"lidar": 1.0, "video": 11.0, "photo": 11.0}[tier]
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
