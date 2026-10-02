"""A-ADJ unit benchmark: does `openings()` recover a real building's door graph?

`scanplan.geometry.rooms.openings` turns a room label image into the opening list that becomes
`plan.adjacency`. Until now nothing measured it -- compliance_matrix.md row 2.2 says so in as
many words: "no ground truth to verify it against". This benchmark gives it one.

HouseLayout3D (Matterport3D buildings, MIT) annotates each storey's floor as planar polygons
and each doorway as a 3D rectangle. Both are *drawn*, not sensed. The earlier decision not to
use the dataset end to end stands: there is no capture here, and synthesising one would put a
synthesiser between the truth and the code, so the number would measure the synthesiser. What
this benchmark does instead is feed the annotated floor straight into the label image, which is
the input `openings()` actually takes, and compare the opening list against the annotated doors.

    free     the storey's floor patches, rasterised onto scanplan's own 2 cm grid. Door reveals
             are their own ~0.1 m2 patches in the dataset, so the walkable floor is connected
             through doorways by the annotation, not by anything this script adds.
    labels   every free cell assigned to the nearest room polygon *through free space*. Walls
             are not free, so two rooms' labels only ever meet where the floor connects them.
             This fill never looks at the door annotations.
    truth    the room pair found by stepping off each door rectangle along its annotated normal.

Two configurations are scored.

    openings-only   labels are the annotated rooms. This is the unit test the brief asks for:
                    `openings()` alone, handed perfect room geometry *and* perfect room
                    identity, with only the opening decision left to make.
    with-splitter   labels come from our own `split_rooms()` run on the same free mask, then
                    matched to annotated rooms by dominant overlap. Strictly harder, and the
                    mapping is lossy when we merge two rooms, so read it as a diagnostic.

Two readings are published for each, and a no-skill baseline is scored beside them, because the
two obvious misreadings of this benchmark both run in our favour:

    recall is not detection    `fill_nearest` grows labels through free space, so wherever the
                               annotated floor joins two rooms their labels MUST meet and
                               `openings()` MUST report the pair. Recall measures the
                               annotation's floor connectivity; precision is the number that
                               measures the code. `summary.recall_is_label_contact_not_detection`
                               decomposes it.
    the control helped         subtracting the negative control RAISES precision, f1 and exact-
                               graph storeys and lowers only recall. It is a correction, not a
                               handicap the result survived. See
                               `summary.control.effect_of_subtracting_it`.

WHAT THIS DOES NOT SHOW is in the output file under `scope`, and it is a long list. Read it.

    python bench/houselayout_adjacency.py [--out FILE] [--scenes A B ...]
Writes bench/results/houselayout_adjacency.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import houselayout3d as hl  # noqa: E402
from scanplan.geometry.rooms import (  # noqa: E402
    DOOR_MAX_M, ROOM_MIN_AREA_M2, openings, split_rooms,
)
from scanplan.geometry.walls import CELL_M, MARGIN_M, Grid  # noqa: E402
from scripts.fetch_houselayout3d import REPO, REVISION  # noqa: E402

OUT = ROOT / "bench" / "results" / "houselayout_adjacency.json"

WIDE_DOOR_MAX_M = 0.90          # the ablation erosion width, for the diagnostic only
WIDE_KEY = f"room_count_if_door_max_were_{WIDE_DOOR_MAX_M:.2f}_m"
BASELINE_GAPS_M = (0.04, 0.08, 0.12, 0.20)
# A no-skill predictor: call two annotated rooms adjacent whenever their drawn floor polygons
# come within this much of each other. It reads the same truth-side geometry openings() is fed
# and makes no use of the code under test, so it is what the headline has to beat for the
# headline to mean anything. Four radii are published rather than one so the reader can see the
# whole precision/recall trade rather than a chosen point.


def rasterise(storey: hl.Storey, *, cell_m: float = CELL_M
              ) -> tuple[Grid, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The storey as (grid, free, rooms_only, room_raster, conn, named), on scanplan's own grid.

    `room_raster` holds label i+1 over room i's polygon; overlapping annotation goes to the
    lower index, which is arbitrary but fixed. `free` is every floor patch, rooms and reveals
    alike -- the walkable floor a perfect capture of this storey would have found.
    `rooms_only` leaves the reveals out, which is the negative control: with no doorway
    anywhere in the floor, anything `openings()` still reports is an artefact of the raster
    rather than a recovered door. `conn` labels the reveals and `named[i]` says whether the
    annotation draws a door on reveal i.
    """
    room_polys = [p.polygon_xy for p in storey.rooms]
    polys = room_polys + [p.polygon_xy for p in storey.connectors]
    allpts = np.concatenate(polys, axis=0)
    lo = allpts.min(axis=0) - MARGIN_M
    hi = allpts.max(axis=0) + MARGIN_M
    size = np.ceil((hi - lo) / cell_m).astype(int) + 1
    grid = Grid(np.zeros((size[1], size[0]), np.float32), lo, cell_m)

    def px(poly: np.ndarray) -> np.ndarray:
        return np.round((poly - lo) / cell_m).astype(np.int32)

    rooms_only = np.zeros(grid.shape, np.uint8)
    for poly in room_polys:
        cv2.fillPoly(rooms_only, [px(poly)], 1)
    free = rooms_only.copy()
    for patch in storey.connectors:
        cv2.fillPoly(free, [px(patch.polygon_xy)], 1)
    rooms = np.zeros(grid.shape, np.int32)
    for i, patch in reversed(list(enumerate(storey.rooms))):
        cv2.fillPoly(rooms, [px(patch.polygon_xy)], i + 1)
    rooms[free == 0] = 0

    # Which reveal a contact happens in, and whether the annotation names a door on it. A
    # reveal is a floor patch drawn inside a wall, so it is evidence of an opening whether or
    # not a door rectangle was annotated there; the pairs that meet in a doorless reveal are
    # the ones a door-only truth set cannot score.
    conn = np.zeros(grid.shape, np.int32)
    for i, patch in reversed(list(enumerate(storey.connectors))):
        cv2.fillPoly(conn, [px(patch.polygon_xy)], i + 1)
    named = np.zeros(len(storey.connectors) + 1, bool)
    reach = max(int(0.20 / cell_m), 1)  # a reveal is only ~0.1 m deep and the door rectangle
                                        # sits on one of its faces, so look either side of it
    for d in storey.doors:
        c = np.round((d.centre_xy - lo) / cell_m).astype(int)
        r0, r1 = max(c[1] - reach, 0), min(c[1] + reach + 1, grid.shape[0])
        c0, c1 = max(c[0] - reach, 0), min(c[0] + reach + 1, grid.shape[1])
        for i in np.unique(conn[r0:r1, c0:c1]):
            named[i] = True
    named[0] = True                     # contact outside every reveal: not a doorless opening
    return grid, free, rooms_only, rooms, conn, named


def fill_nearest(free: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Every free cell labelled with the nearest seed label, distance measured through free.

    A plain simultaneous breadth-first flood from all seeds at once: each round, an unlabelled
    free cell adjacent to a labelled one takes the smallest label among its labelled
    neighbours. Ties go to the lower label, so the result does not depend on iteration order.
    Only the reveals under doorways are unlabelled to begin with, so this converges in a few
    rounds. It is deliberately blind to the door annotations -- the labels have to meet where
    the floor is open, and nowhere else.
    """
    lab = seeds.copy()
    todo = (free > 0) & (lab == 0)
    big = np.iinfo(np.int32).max
    while todo.any():
        cand = np.where(lab > 0, lab, big)
        best = np.full_like(cand, big)
        for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
            best = np.minimum(best, np.roll(cand, shift, axis=axis))
        grew = todo & (best < big)
        if not grew.any():
            break                       # free space not reachable from any room: leave it 0
        lab[grew] = best[grew]
        todo &= ~grew
    return lab


def pair_gaps(room_raster: np.ndarray, n_rooms: int, cell_m: float) -> dict:
    """For EVERY room pair, how much non-floor there is between the two annotated polygons.

    0.0 means the two polygons touch: the annotation drew no wall there, so whatever joins them
    is an open boundary and not a doorway. A few centimetres means a real partition. This is the
    measurement that decides whether a predicted opening is a doorway, an open connection, or a
    wall the code reached across.

    Every pair is measured, not only the predicted and true ones, because the no-skill baseline
    below needs the gap for pairs neither side names.
    """
    out = {}
    for a in range(1, n_rooms + 1):
        if (room_raster == a).sum() == 0:
            continue
        dist = cv2.distanceTransform((room_raster != a).astype(np.uint8), cv2.DIST_L2, 5)
        for b in range(a + 1, n_rooms + 1):
            cells = dist[room_raster == b]
            if len(cells):
                # a cell 4-adjacent to room a has distance 1, so subtract that one step
                out[(a, b)] = round(max(float(cells.min()) - 1.0, 0.0) * cell_m, 3)
        del dist
    return out


def component_pairs(free: np.ndarray, room_raster: np.ndarray, n_rooms: int) -> set:
    """Room pairs with at least one free-space component in common: joined by walkable floor.

    `reachability()` below reports the same relation from each room's *dominant* component, which
    is what the per-storey record publishes. This version takes every component a room overlaps,
    so it is the honest upper bound on what any label-contact method could report: two rooms with
    no walkable floor between them anywhere cannot be brought into label contact except by
    bridging a wall. The per-storey record publishes how far the two readings differ.
    """
    n, comp = cv2.connectedComponents(free, connectivity=4)[:2]
    comps = {}
    for i in range(1, n_rooms + 1):
        comps[i] = {int(c) for c in np.unique(comp[room_raster == i]) if c > 0}
    pairs = set()
    for a in range(1, n_rooms + 1):
        for b in range(a + 1, n_rooms + 1):
            if comps[a] & comps[b]:
                pairs.add((a, b))
    return pairs


def no_skill_baseline(gaps: dict, truth: set) -> dict:
    """Score "the two drawn room polygons come within d metres" against the same truth.

    This predictor never runs `openings()`, never rasterises a label image and never looks at a
    doorway reveal; it reads the truth side's own floor polygons and thresholds the distance
    between them. If it scored as well as the headline, the headline would be measuring the
    dataset's geometry rather than our code.
    """
    out = {}
    for d in BASELINE_GAPS_M:
        pred = {p for p, g in gaps.items() if g <= d}
        out[f"{d:.2f}"] = {"tp": len(pred & truth), "fp": len(pred - truth),
                           "fn": len(truth - pred)}
    return out


def predicted_pairs(labels: np.ndarray, grid: Grid, free: np.ndarray) -> dict:
    found = openings(labels, grid, free)
    return {tuple(sorted(o.rooms)): o.width_m for o in found}


def dominant_map(ours: np.ndarray, truth: np.ndarray) -> dict[int, int]:
    """Our label -> the annotated room it covers most of."""
    out = {}
    for lbl in range(1, int(ours.max()) + 1):
        vals = truth[ours == lbl]
        vals = vals[vals > 0]
        if len(vals) == 0:
            continue
        out[lbl] = int(np.bincount(vals).argmax())
    return out


def score(pred: set, true: set) -> dict:
    tp = len(pred & true)
    return {"n_pred": len(pred), "n_true": len(true), "tp": tp,
            "fp": len(pred - true), "fn": len(true - pred),
            "precision": tp / len(pred) if pred else None,
            "recall": tp / len(true) if true else None,
            "exact": pred == true}


def doorless_contact(labels: np.ndarray, pair: tuple[int, int], conn: np.ndarray,
                     named: np.ndarray) -> dict:
    """Whether labels a and b come into contact inside a reveal the annotation names no door on.

    The contact region is found the same way `openings()` finds it, with a 5x5 dilation of each
    label. `only` is the strict reading -- every reveal the two labels meet in is doorless, so
    the opening the code reported is one the dataset draws but does not name. It is reported
    for the true positives as well as the false ones; a flag that fires on both would say
    nothing.
    """
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    overlap = (cv2.dilate((labels == pair[0]).astype(np.uint8), k)
               & cv2.dilate((labels == pair[1]).astype(np.uint8), k))
    ids = [int(i) for i in np.unique(conn[overlap > 0]) if i > 0]
    doorless = [i for i in ids if not named[i]]
    return {"any": bool(doorless), "only": bool(doorless) and len(doorless) == len(ids)}


def run_storey(storey: hl.Storey) -> dict:
    grid, free, rooms_only, room_raster, conn, named = rasterise(storey)
    truth = {(a + 1, b + 1) for a, b in storey.edges}

    # The control first: no doorways in the floor at all. Anything reported here is reported
    # without a doorway to report, so it is a raster artefact and cannot count either way.
    control = set(predicted_pairs(room_raster, grid, rooms_only))
    truth_live = truth - control
    labels = fill_nearest(free, room_raster)
    pred = predicted_pairs(labels, grid, free)
    pred_live = {p: w for p, w in pred.items() if p not in control}

    rec = {
        "scene": storey.scene, "storey": storey.index, "floor_z_m": round(storey.z, 3),
        "grid_px": list(grid.shape), "n_rooms": len(storey.rooms),
        "n_connector_patches": len(storey.connectors),
        "room_area_m2": [round(p.area_m2, 2) for p in storey.rooms],
        "n_doors": len(storey.doors),
        "door_width_m": sorted(round(d.width_m, 2) for d in storey.doors),
        "exterior_doors": storey.exterior_doors, "unplaced_doors": storey.unplaced_doors,
        "same_room_doors": storey.same_room_doors,
        "true_pairs": sorted(truth),
        "free_components": int(cv2.connectedComponentsWithStats(free, connectivity=4)[0] - 1),
        "rooms_reachable_from_each_other": reachability(free, room_raster, len(storey.rooms)),
        # How many separate floor regions the annotation draws once the doorways are taken out.
        # If this is far below n_rooms, the rooms are not separated by geometry at all and no
        # splitter working from floor coverage could ever recover them; if it equals n_rooms,
        # they are, and a splitter that merges them is failing for its own reasons.
        "floor_regions_with_doorways_deleted": int(
            cv2.connectedComponentsWithStats(rooms_only, connectivity=4)[0] - 1),
        "control_pairs_no_doorway_in_floor": sorted(control),
        "true_pairs_lost_to_control": sorted(truth & control),
    }
    gaps = pair_gaps(room_raster, len(storey.rooms), grid.cell_m)
    named_or_pred = set(pred) | truth
    rec["pair_wall_gap_m"] = {f"{a}-{b}": g for (a, b), g in sorted(gaps.items())
                              if (a, b) in named_or_pred}
    rec["control_pair_wall_gap_m"] = sorted(gaps[p] for p in control if p in gaps)
    rec["no_skill_baseline"] = no_skill_baseline(gaps, truth)
    rec["openings_only_all_pairs"] = score(set(pred), truth) | {
        "pairs": sorted(pred),
        "width_m": {f"{a}-{b}": round(w, 2) for (a, b), w in sorted(pred.items())},
    }

    # What recall is actually made of. `openings()` reports a pair when the two labels come into
    # contact; `fill_nearest` grows the labels through free space, so wherever the annotated
    # floor joins two rooms the labels MUST meet. Recall is therefore bounded below by the
    # annotation's own floor connectivity, and the question is whether any of it came from the
    # code: the width filter is the only part of openings() that can refuse a pair it has
    # contact for, so it is measured separately.
    joined = component_pairs(free, room_raster, len(storey.rooms))
    dominant = {tuple(p) for p in rec["rooms_reachable_from_each_other"]}
    unfiltered = {tuple(sorted(o.rooms)) for o in openings(labels, grid, free,
                                                           door_max_m=float("inf"))}
    discarded = unfiltered - set(pred)
    rec["recall_decomposition"] = {
        "true_pairs": len(truth_live),
        "joined_by_walkable_floor": len(truth_live & joined),
        "of_those_predicted": len(truth_live & joined & set(pred_live)),
        "predicted_with_no_walkable_floor_between_them":
            sorted(p for p in truth_live - joined if p in pred_live),
        "missed": sorted(truth_live - set(pred_live)),
        "missed_that_were_joined_by_walkable_floor":
            sorted(p for p in truth_live - set(pred_live) if p in joined),
        "pairs_discarded_as_a_whole_open_side": sorted(discarded),
        "true_pairs_discarded_as_a_whole_open_side": sorted(discarded & truth_live),
        "dominant_component_reading_differs_on": sorted(joined ^ dominant),
    }
    rec["openings_only"] = score(set(pred_live), truth_live) | {
        "pairs": sorted(pred_live),
        "width_m": {f"{a}-{b}": round(w, 2) for (a, b), w in sorted(pred_live.items())},
        "true_pair_wall_gap_m": sorted(gaps[p] for p in truth_live if p in gaps),
        "false_positives": [
            {"pair": list(p), "reported_width_m": round(w, 2), "wall_gap_m": gaps.get(p),
             "doorless_reveal": doorless_contact(labels, p, conn, named)}
            for p, w in sorted(pred_live.items()) if p not in truth_live],
        "true_positives_doorless_reveal": [
            doorless_contact(labels, p, conn, named)
            for p in sorted(set(pred_live) & truth_live)],
        "missed": sorted(truth_live - set(pred_live)),
        "exact_if_doorless_reveals_set_aside": set(
            p for p in pred_live
            if not doorless_contact(labels, p, conn, named)["only"]) == truth_live,
    }

    ours = split_rooms(free, grid)
    mapping = dominant_map(ours, room_raster)
    pred_a = set()
    for a, b in predicted_pairs(ours, grid, free):
        ma, mb = mapping.get(a), mapping.get(b)
        if ma and mb and ma != mb:
            pred_a.add((min(ma, mb), max(ma, mb)))
    rec["with_splitter"] = score(pred_a - control, truth_live) | {
        "our_room_count": int(ours.max()),
        "annotated_rooms_we_hit": len(set(mapping.values())),
        "pairs": sorted(pred_a),
    }
    # Diagnostic, not a proposal. DOOR_MAX_M is 0.70 m, set on UK flats; most of the doors
    # annotated here are wider than that, so an erosion sized for 0.70 m leaves the neck
    # standing and the whole storey comes back as one room. The distribution is computed in
    # `summary.annotated_door_widths` rather than restated here, so that no literal in this
    # file can disagree with the run. Re-running the split at WIDE_DOOR_MAX_M shows whether
    # that is the whole story. It does not say 0.90 is the right constant for our captures.
    wide = split_rooms(free, grid, door_max_m=WIDE_DOOR_MAX_M)
    rec["with_splitter"][WIDE_KEY] = int(wide.max())
    return rec


def reachability(free: np.ndarray, room_raster: np.ndarray, n_rooms: int) -> list[list[int]]:
    """Which annotated room pairs are joined by walkable floor at all, ignoring width.

    An upper bound on anything `openings()` could possibly report, and the check that the
    rasterisation did not quietly sever the doorways: if a door's two rooms are not even in the
    same free-space component, the construction is broken, not the code under test.
    """
    n, comp = cv2.connectedComponents(free, connectivity=4)[:2]
    by_comp: dict[int, set[int]] = {}
    for i in range(1, n_rooms + 1):
        cells = comp[room_raster == i]
        if len(cells) == 0:
            continue
        by_comp.setdefault(int(np.bincount(cells).argmax()), set()).add(i)
    pairs = set()
    for group in by_comp.values():
        g = sorted(group)
        for i, a in enumerate(g):
            for b in g[i + 1:]:
                pairs.add((a, b))
    return sorted(list(p) for p in pairs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--scenes", nargs="*", default=None)
    args = ap.parse_args()

    t0 = time.time()
    records = []
    for scene in (args.scenes or hl.scenes()):
        for storey in hl.storeys(scene, room_min_area_m2=ROOM_MIN_AREA_M2):
            if not storey.edges:
                records.append({"scene": scene, "storey": storey.index,
                                "skipped": "no door joins two annotated rooms on this storey",
                                "n_rooms": len(storey.rooms), "n_doors": len(storey.doors),
                                "exterior_doors": storey.exterior_doors,
                                "same_room_doors": storey.same_room_doors})
                continue
            rec = run_storey(storey)
            records.append(rec)
            o = rec["openings_only"]
            print(f"{scene} s{storey.index}: rooms={rec['n_rooms']:2d} true={o['n_true']:2d} "
                  f"pred={o['n_pred']:2d} tp={o['tp']:2d} fp={o['fp']:2d} fn={o['fn']:2d} "
                  f"{'exact' if o['exact'] else ''}", flush=True)

    scored = [r for r in records if "openings_only" in r]
    fps = [f for r in scored for f in r["openings_only"]["false_positives"]]
    tp_flags = [f for r in scored for f in r["openings_only"]["true_positives_doorless_reveal"]]
    summary = {}
    for key in ("openings_only", "openings_only_all_pairs", "with_splitter"):
        tp = sum(r[key]["tp"] for r in scored)
        fp = sum(r[key]["fp"] for r in scored)
        fn = sum(r[key]["fn"] for r in scored)
        summary[key] = {
            "storeys": len(scored),
            "true_pairs": tp + fn, "predicted_pairs": tp + fp,
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "f1": round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0,
            "exact_graph_storeys": sum(r[key]["exact"] for r in scored),
        }
    summary["openings_only"]["exact_graph_storeys_if_doorless_reveals_set_aside"] = sum(
        r["openings_only"]["exact_if_doorless_reveals_set_aside"] for r in scored)
    head = summary["openings_only"]
    loose = summary["openings_only_all_pairs"]
    spl = summary["with_splitter"]
    n_scenes = len({r["scene"] for r in scored})
    head["what_it_means"] = (
        "the headline. Door pairs the control did not already produce, so every pair counted "
        "needed a doorway in the floor to be reported. Read `recall` through "
        "`recall_is_label_contact_not_detection` before quoting it.")
    loose["what_it_means"] = (
        "the same scoring without the control subtracted. Published for comparison only: both "
        "its numerator and its denominator contain pairs the rasterisation hands over for free. "
        "This is also the configuration the no-skill baseline is scored against, since the "
        "baseline has no control to subtract.")

    # What recall is made of. Derived, not asserted: the per-storey decomposition is summed here
    # and the sentence is written from the sums, so it cannot drift from the run.
    rds = [r["recall_decomposition"] for r in scored]
    rd = {
        "true_pairs": sum(d["true_pairs"] for d in rds),
        "pairs_whose_rooms_are_joined_by_walkable_floor":
            sum(d["joined_by_walkable_floor"] for d in rds),
        "of_those_predicted": sum(d["of_those_predicted"] for d in rds),
        "predicted_with_no_walkable_floor_between_them":
            sum(len(d["predicted_with_no_walkable_floor_between_them"]) for d in rds),
        "missed": sum(len(d["missed"]) for d in rds),
        "missed_that_were_joined_by_walkable_floor":
            sum(len(d["missed_that_were_joined_by_walkable_floor"]) for d in rds),
        "pairs_the_width_filter_discarded":
            sum(len(d["pairs_discarded_as_a_whole_open_side"]) for d in rds),
        "true_pairs_the_width_filter_discarded":
            sum(len(d["true_pairs_discarded_as_a_whole_open_side"]) for d in rds),
        "storeys_where_the_dominant_component_reading_differs":
            sum(bool(d["dominant_component_reading_differs_on"]) for d in rds),
    }
    joined = rd["pairs_whose_rooms_are_joined_by_walkable_floor"]
    rd["what_it_means"] = (
        f"recall {head['recall']} is NOT a detection rate. fill_nearest grows each room's label "
        f"through free space, so wherever the annotated floor joins two rooms their labels MUST "
        f"come into contact, and openings() reports a pair on contact. Of the {rd['true_pairs']} "
        f"live truth pairs, {joined} have their two rooms joined by walkable floor and "
        f"{rd['of_those_predicted']} of those {joined} were predicted"
        + (" -- all of them" if rd["of_those_predicted"] == joined else "")
        + f". The {rd['missed']} misses are pairs the rasterisation left in different free-space "
        f"components, {rd['missed_that_were_joined_by_walkable_floor']} of them joined by "
        f"walkable floor. The only part of openings() that can refuse a pair it has contact for "
        f"is the width filter (> 2.5 x DOOR_MAX_M is discarded as a whole open side); it "
        f"discarded {rd['pairs_the_width_filter_discarded']} pairs here, "
        f"{rd['true_pairs_the_width_filter_discarded']} of them real door pairs. So recall "
        f"measures the annotation's own floor connectivity, not discrimination by openings(). "
        f"The discriminating number is precision {head['precision']} on {head['fp']} false "
        f"positives. A further {rd['predicted_with_no_walkable_floor_between_them']} truth "
        f"pair(s) were predicted with no walkable floor between the two rooms at all, which is "
        f"the same wall-bridging the negative control measures rather than a door being found.")
    summary["recall_is_label_contact_not_detection"] = rd

    widths = sorted(w for r in scored for w in r["door_width_m"])
    wider = sum(w > DOOR_MAX_M for w in widths)
    summary["annotated_door_widths"] = {
        "note": "every door the truth derivation placed on a scored storey, as annotated. "
                "Published because DOOR_MAX_M is the constant the with_splitter block fails on, "
                "so the distribution it is being compared against must be visible rather than "
                "summarised as a modal band.",
        "n": len(widths),
        "door_max_m": DOOR_MAX_M,
        "min_m": widths[0], "max_m": widths[-1],
        "median_m": round(float(np.median(widths)), 2),
        "wider_than_door_max_m": wider,
        "at_or_below_door_max_m": len(widths) - wider,
        "share_wider_than_door_max_m": round(wider / len(widths), 3),
        "deciles_m": [round(float(q), 2)
                      for q in np.percentile(widths, np.arange(10, 100, 10))],
    }

    base = {}
    for d in BASELINE_GAPS_M:
        k = f"{d:.2f}"
        tp = sum(r["no_skill_baseline"][k]["tp"] for r in scored)
        fp = sum(r["no_skill_baseline"][k]["fp"] for r in scored)
        fn = sum(r["no_skill_baseline"][k]["fn"] for r in scored)
        base[k] = {"tp": tp, "fp": fp, "fn": fn,
                   "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                   "recall": round(tp / (tp + fn), 4) if tp + fn else None,
                   "f1": round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0}
    best = max(base, key=lambda k: base[k]["f1"])
    summary["no_skill_baseline"] = {
        "note": "a predictor that never runs openings(): call two annotated rooms adjacent when "
                "their drawn floor polygons come within d metres of each other. It reads only "
                "truth-side geometry. Scored against the same unsubtracted truth as "
                "openings_only_all_pairs, because it has no control to subtract.",
        "by_gap_m": base,
        "best_f1": base[best]["f1"],
        "best_gap_m": float(best),
        "openings_f1_same_truth": loose["f1"],
        "what_it_means": (
            f"the best no-skill radius scores f1 {base[best]['f1']} against openings()' "
            f"{loose['f1']} on the same truth, so the headline is not a restatement of the "
            f"annotation's geometry. It is the margin that makes the result non-tautological, "
            f"and it is published here rather than claimed."),
    }

    strict_pairs = sum(len(r["control_pairs_no_doorway_in_floor"]) for r in scored)
    swallowed = sum(len(r["true_pairs_lost_to_control"]) for r in scored)
    cgaps = sorted(g for r in scored for g in r["control_pair_wall_gap_m"])
    summary["control"] = {
        "note": "openings() run on the same storeys with every doorway reveal deleted from the "
                "floor. These pairs are reported with no doorway present to report, so they "
                "measure the rasterisation and the 5x5 contact dilation, not the code's ability "
                "to find a door. They are removed from both sides of the headline score.",
        "pairs": strict_pairs,
        "true_door_pairs_it_swallows": swallowed,
        "wall_gap_m_range": [cgaps[0], cgaps[-1]] if cgaps else None,
        "pairs_whose_room_polygons_touch": sum(g == 0.0 for g in cgaps),
        "pairs_separated_by_a_real_partition": sum(g > 0.0 for g in cgaps),
        "effect_of_subtracting_it": {
            "note": "which direction the control moved the published numbers. Stated explicitly "
                    "because subtracting a negative control is usually a penalty and here it is "
                    "not: it removes far more false positives than true positives.",
            "precision": [loose["precision"], head["precision"]],
            "recall": [loose["recall"], head["recall"]],
            "f1": [loose["f1"], head["f1"]],
            "exact_graph_storeys": [loose["exact_graph_storeys"],
                                    head["exact_graph_storeys"]],
            "what_it_means": (
                f"subtracting the control RAISED precision {loose['precision']} -> "
                f"{head['precision']}, RAISED f1 {loose['f1']} -> {head['f1']} and RAISED exact-"
                f"graph storeys {loose['exact_graph_storeys']} -> {head['exact_graph_storeys']} "
                f"of {head['storeys']}. Only recall fell, {loose['recall']} -> {head['recall']}. "
                f"The control is not a handicap the result survived; it is a correction that "
                f"improved every reading but one, because the {strict_pairs} pairs it removes "
                f"are mostly pairs openings() should not have reported "
                f"({swallowed} of them were real door pairs)."),
        },
    }
    rooms_n = sum(r["n_rooms"] for r in scored)
    regions_n = sum(r["floor_regions_with_doorways_deleted"] for r in scored)
    ours_n = sum(r["with_splitter"]["our_room_count"] for r in scored)
    wide_n = sum(r["with_splitter"][WIDE_KEY] for r in scored)
    summary["how_separable_the_annotated_rooms_are"] = {
        "note": "the annotated rooms, against the number of separate floor regions left when "
                "every doorway reveal is deleted. This bounds any room splitter that works from "
                "floor coverage: rooms that share a floor region with no boundary between them "
                "cannot be told apart from the floor alone. It is a measurement of the DATA, so "
                "it is also the figure that says whether a poor room count is the data's fault "
                "or ours.",
        "annotated_rooms": rooms_n,
        "floor_regions_with_doorways_deleted": regions_n,
        "share_separable": round(regions_n / rooms_n, 3),
        "our_rooms_from_split_rooms": ours_n,
        f"our_rooms_if_door_max_were_{WIDE_DOOR_MAX_M:.2f}_m": wide_n,
        "what_it_means": (
            f"{regions_n} of {rooms_n} annotated rooms ({regions_n / rooms_n:.1%}) ARE separated "
            f"by drawn geometry once the doorway reveals are removed, so the data imposes almost "
            f"no ceiling here. split_rooms() recovers {ours_n} of them, rising to {wide_n} when "
            f"the erosion is widened from DOOR_MAX_M = {DOOR_MAX_M:.2f} m to "
            f"{WIDE_DOOR_MAX_M:.2f} m. "
            f"A splitter that merges rooms the geometry separates is failing for its own "
            f"reasons, not against a limit in the annotation."),
    }

    out = {
        "benchmark": "houselayout_adjacency",
        "unit_under_test": "scanplan.geometry.rooms.openings",
        "dataset": "HouseLayout3D (Matterport3D buildings, MIT licence)",
        # Named in the artifact because clean_clone_check.sh regenerates this file and compares
        # it against the committed copy: if the snapshot moves, the reader should be able to see
        # that it moved rather than read a DIFFERS as a bug in our code.
        # scripts/fetch_houselayout3d.py pins the revision so it cannot move silently.
        "dataset_source": {"repo_id": REPO, "repo_type": "dataset", "revision": REVISION},
        "constants_from_our_side": {"cell_m": CELL_M, "margin_m": MARGIN_M,
                                    "room_min_area_m2": ROOM_MIN_AREA_M2},
        "summary": summary,
        "false_positives": {
            "note": "pairs reported only when the doorways are present, that no annotated door "
                    "joins. Read with care: the truth here is DOORS, and openings() reports "
                    "open connections too by design, so a pair that two rooms genuinely share "
                    "through an archway counts against it. wall_gap_m is the thinnest non-floor "
                    "between the two room polygons, which does NOT separate the two cases -- a "
                    "pair joined by a door is also walled everywhere else -- so no mechanical "
                    "split of these is offered. They are listed per storey instead.",
            "total": len(fps),
            "meet_only_in_reveals_with_no_door_annotated":
                sum(f["doorless_reveal"]["only"] for f in fps),
            "meet_in_at_least_one_such_reveal": sum(f["doorless_reveal"]["any"] for f in fps),
            "same_flag_on_the_true_positives": {
                "n": len(tp_flags),
                "only": sum(f["only"] for f in tp_flags),
                "any": sum(f["any"] for f in tp_flags),
            },
            "reported_width_m": sorted(f["reported_width_m"] for f in fps),
            "wall_gap_m": sorted(f["wall_gap_m"] for f in fps if f["wall_gap_m"] is not None),
        },
        # Every figure in this section is interpolated from the run above. Nothing here is a
        # literal: an earlier revision wrote "139 of 141", "recall 0.03" and "0.78-0.81 m" as
        # strings, which means a rerun on a different snapshot would have shipped a scope
        # section contradicting its own summary block.
        "scope": {
            "what_this_validates": [
                "openings() given PERFECT room geometry and perfect room identity: the floor "
                "polygons are drawn by a human, so nothing here is sensed, fused or segmented.",
                f"That the opening list keys the right pairs of rooms: {head['tp']} of "
                f"{head['true_pairs']} door pairs across {head['storeys']} storeys of "
                f"{n_scenes} real buildings, with the raster's own free pairs subtracted first. "
                f"The {head['fn']} it misses are named per storey under `missed`. This is a "
                f"KEYING result, not a detection result -- see the next entry.",
                f"That the opening decision beats a no-skill reading of the same geometry. "
                f"Thresholding the distance between the drawn room polygons scores f1 at best "
                f"{base[best]['f1']} (at d = {float(best):.2f} m) against openings()' "
                f"{loose['f1']} on the same unsubtracted truth, so the headline is not the "
                f"annotation restated.",
                f"That the width filter -- width > 2.5 x DOOR_MAX_M is discarded as a whole open "
                f"side -- throws away no real doorway in this set: it discarded "
                f"{rd['pairs_the_width_filter_discarded']} pairs, of which "
                f"{rd['true_pairs_the_width_filter_discarded']} were real door pairs.",
                "A-ADJ, which compliance_matrix.md row 2.2 reports as having no ground truth of "
                "any kind. It now has one, at the unit level only.",
            ],
            "what_this_does_not_validate": [
                "The pipeline end to end. There is no capture in this dataset. Depth, poses, "
                "fusion, floor finding, wall finding and room splitting are all bypassed. "
                "Nothing here says a plan built from a real walk has the right adjacency.",
                f"RECALL AS A DETECTION RATE. recall {head['recall']} must not be read as "
                f"\"openings() found {head['tp']} of {head['true_pairs']} doors\". fill_nearest "
                f"grows each room's label through free space, so label contact is GUARANTEED "
                f"wherever the annotated floor joins two rooms. Of the {rd['true_pairs']} live "
                f"truth pairs, {rd['pairs_whose_rooms_are_joined_by_walkable_floor']} are so "
                f"joined and {rd['of_those_predicted']} of those were predicted; the "
                f"{rd['missed']} misses are pairs the rasterisation left in different free-space "
                f"components. The width filter, the only part of openings() that can refuse a "
                f"pair it has contact for, fired on "
                f"{rd['true_pairs_the_width_filter_discarded']} truth pairs. Recall therefore "
                f"measures the annotation's floor connectivity. The number that measures "
                f"openings() is precision {head['precision']}, on {head['fp']} false positives.",
                f"Room splitting. In the headline configuration the room labels ARE the "
                f"annotation, so split_rooms() does not run. This benchmark does not excuse it. "
                f"The with_splitter block runs it on the same perfect floor and it recovers "
                f"almost nothing -- recall {spl['recall']}, {spl['tp']} of {spl['true_pairs']} "
                f"pairs -- because DOOR_MAX_M is {DOOR_MAX_M:.2f} m while the "
                f"{summary['annotated_door_widths']['n']} doors annotated here run "
                f"{summary['annotated_door_widths']['min_m']} to "
                f"{summary['annotated_door_widths']['max_m']} m with a median of "
                f"{summary['annotated_door_widths']['median_m']:.2f} m and "
                f"{summary['annotated_door_widths']['share_wider_than_door_max_m']:.1%} of them "
                f"wider than {DOOR_MAX_M:.2f} m "
                f"({summary['annotated_door_widths']['at_or_below_door_max_m']} are at or below "
                f"it). An erosion sized for {DOOR_MAX_M:.2f} m never pinches most of those off "
                f"and most storeys come back as a single room. {WIDE_KEY} is published per "
                f"storey as "
                f"evidence for that reading. It is NOT a proposal to change the constant: "
                f"{DOOR_MAX_M:.2f} was set on our own captures and would need its own measurement "
                f"to move.",
                "Opening WIDTH. What openings() measures is the clear width of the floor neck, "
                "which is not the door leaf the dataset annotates. The two are not compared. "
                "door_width_m is published per storey for the reader only.",
                "Anything about our own captures. These are large American houses as a drawn "
                "annotation; the UK flats the pipeline is built for are not represented, and "
                "their doors are narrower, which is exactly the constant that fails above.",
                f"Precision in the ordinary sense. The truth here is DOORS, and openings() is "
                f"documented to report open connections too. "
                f"{sum(f['doorless_reveal']['only'] for f in fps)} of the {len(fps)} false "
                f"positives are pairs whose labels meet ONLY inside a floor patch the annotation "
                f"drew inside a wall and named no door on -- an opening the dataset shows but "
                f"does not label. The same flag fires on "
                f"{sum(f['any'] for f in tp_flags)} of the {len(tp_flags)} true positives, so it "
                f"is not a blanket excuse; but it does mean the reported precision is a lower "
                f"bound and the true figure against real adjacency is unmeasured.",
            ],
            "controls_run": [
                f"Negative control: every storey is also scored with the doorway reveals deleted "
                f"from the floor, so no doorway exists to find. openings() still reports "
                f"{strict_pairs} pairs, {swallowed} of them real door pairs. Their room polygons "
                f"sit {cgaps[0] * 100:.0f}-{cgaps[-1] * 100:.0f} cm apart "
                f"({summary['control']['pairs_whose_room_polygons_touch']} of them touch "
                f"outright, so the annotation drew no partition there at all; the other "
                f"{summary['control']['pairs_separated_by_a_real_partition']} are across a thin "
                f"wall) and the 5x5 contact dilation in openings() reaches 4 cm from each label, "
                f"so it bridges them. All {strict_pairs} are subtracted from both sides of the "
                f"headline.",
                f"Which direction that subtraction moved the result, because a reader may assume "
                f"a control is a handicap. It is not one here: precision {loose['precision']} -> "
                f"{head['precision']}, f1 {loose['f1']} -> {head['f1']} and exact-graph storeys "
                f"{loose['exact_graph_storeys']} -> {head['exact_graph_storeys']} all ROSE; only "
                f"recall fell, {loose['recall']} -> {head['recall']}. The full statement is in "
                f"summary.control.effect_of_subtracting_it.",
                "That bridging is a real property of the code, not of this dataset: openings() "
                "has no minimum width, so a pair bridged across a wall is published into "
                "plan.adjacency with a width near zero. On our own 2 cm grid any partition "
                "thinner than about 8 cm of unobserved floor is at risk.",
                "The doorless-reveal flag is reported for the true positives as well as the "
                "false ones, so a flag that fired on everything would be visible.",
                f"A no-skill baseline on the truth side's own geometry, at "
                f"{len(BASELINE_GAPS_M)} radii, so the headline can be compared against doing "
                f"nothing. Best f1 {base[best]['f1']} against {loose['f1']}.",
            ],
            "truth_derivation": [
                "The dataset has no room entities and no door-to-room association; both are "
                "derived in bench/houselayout3d.py from the annotation alone.",
                "A room is a floor-facing horizontal entity of at least ROOM_MIN_AREA_M2, which "
                "is our own constant. A different threshold would give a different room set.",
                "A door's two rooms are found by stepping off the rectangle along its annotated "
                "normal. Doors that find a room on one side are counted as exterior and dropped; "
                "doors that find the same room on both sides mean the annotation did not split "
                "that space, and are dropped too. Both counts are published per storey.",
            ],
        },
        "storeys": records,
    }
    # No wall clock in the file: it has to be byte-identical from a clean clone (A-DET).
    print(f"\n{time.time() - t0:.1f} s", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n")
    for key, s in summary.items():
        if "precision" not in s:
            continue
        print(f"\n{key}: precision {s['precision']} recall {s['recall']} f1 {s['f1']}  "
              f"exact graph {s['exact_graph_storeys']}/{s['storeys']} storeys  "
              f"({s['tp']} tp, {s['fp']} fp, {s['fn']} fn)")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
