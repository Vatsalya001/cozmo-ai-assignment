"""The A-ADJ unit result must keep saying only what it measured.

`bench/results/houselayout_adjacency.json` is the only external check `plan.adjacency` has, and
the dataset it uses annotates DOORS while `openings()` reports openings. That gap is the whole
reason the number is defensible or not, so the properties that make it defensible are asserted
here rather than left to a reader of the prose:

  - the negative control is subtracted from both sides, not just the false positives
  - the direction the control moved EVERY published number, not only recall
  - the flag used to explain the false positives does not fire on the true positives
  - recall is published as label contact rather than as a detection rate
  - a no-skill baseline on the same truth is published, and beaten
  - the prose in the file is interpolated from the file's own numbers, not written as literals
  - the arithmetic in `summary` is the arithmetic in `storeys`

The benchmark itself needs data/external/houselayout3d, which is fetched rather than committed;
the result file is committed, so these run anywhere.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULT = Path(__file__).resolve().parents[1] / "bench" / "results" / "houselayout_adjacency.json"


@pytest.fixture(scope="module")
def adj():
    assert RESULT.is_file(), (
        "bench/results/houselayout_adjacency.json is committed on purpose: it is the only "
        "ground truth plan.adjacency has ever been measured against")
    return json.loads(RESULT.read_text())


@pytest.fixture(scope="module")
def scored(adj):
    return [r for r in adj["storeys"] if "openings_only" in r]


def test_the_headline_counts_are_the_sum_of_the_per_storey_counts(adj, scored):
    s = adj["summary"]["openings_only"]
    for field in ("tp", "fp", "fn"):
        assert s[field] == sum(r["openings_only"][field] for r in scored)
    assert s["true_pairs"] == s["tp"] + s["fn"]
    assert s["precision"] == pytest.approx(s["tp"] / (s["tp"] + s["fp"]), abs=1e-4)
    assert s["recall"] == pytest.approx(s["tp"] / s["true_pairs"], abs=1e-4)


def test_the_control_is_subtracted_from_the_truth_as_well_as_the_predictions(adj, scored):
    """The control exists because the raster hands over pairs for free, and a large minority of
    them are real door pairs. Dropping those from the predictions but leaving them in the truth
    would turn a correction into a penalty; leaving them in both would inflate recall. They come
    out of both, so the headline denominator must be smaller than the unsubtracted one by
    exactly the number the control swallows."""
    strict = adj["summary"]["openings_only"]
    loose = adj["summary"]["openings_only_all_pairs"]
    swallowed = adj["summary"]["control"]["true_door_pairs_it_swallows"]
    assert swallowed > 0, "a control that catches nothing has not been shown to be a control"
    assert loose["true_pairs"] - strict["true_pairs"] == swallowed
    assert strict["recall"] <= loose["recall"] + 1e-9, (
        "subtracting the control must not be able to raise recall")

    for r in scored:
        control = {tuple(p) for p in r["control_pairs_no_doorway_in_floor"]}
        assert not (set(map(tuple, r["openings_only"]["pairs"])) & control)
        assert not (set(map(tuple, r["true_pairs_lost_to_control"])) - control)


def test_the_direction_the_control_moved_every_number_is_published(adj):
    """A recall-only guard hides the asymmetry. Subtracting this control RAISES precision, f1
    and exact-graph storeys and lowers only recall, which means it is a correction and not a
    handicap the result survived -- the opposite of how a negative control usually reads. If the
    file ever stops saying so, or the direction ever silently flips, this fails."""
    strict = adj["summary"]["openings_only"]
    loose = adj["summary"]["openings_only_all_pairs"]
    eff = adj["summary"]["control"]["effect_of_subtracting_it"]

    assert eff["precision"] == [loose["precision"], strict["precision"]]
    assert eff["recall"] == [loose["recall"], strict["recall"]]
    assert eff["f1"] == [loose["f1"], strict["f1"]]
    assert eff["exact_graph_storeys"] == [loose["exact_graph_storeys"],
                                         strict["exact_graph_storeys"]]

    assert strict["precision"] > loose["precision"], "the control raised precision; say so"
    assert strict["f1"] > loose["f1"], "the control raised f1; say so"
    assert strict["exact_graph_storeys"] > loose["exact_graph_storeys"]
    assert strict["recall"] < loose["recall"], "recall is the only reading that fell"

    said = eff["what_it_means"]
    assert "RAISED" in said and "Only recall fell" in said
    assert f"{loose['precision']} -> {strict['precision']}" in said
    assert f"{loose['f1']} -> {strict['f1']}" in said
    assert f"{loose['recall']} -> {strict['recall']}" in said
    assert f"{loose['exact_graph_storeys']} -> {strict['exact_graph_storeys']}" in said


def test_recall_is_published_as_label_contact_and_not_as_detection(adj, scored):
    """139 of 141 must not be readable as "openings() found 139 doors". `fill_nearest` grows
    labels through free space, so label contact is guaranteed wherever the annotated floor joins
    two rooms; the only part of openings() that can refuse a pair it has contact for is the
    width filter. Both halves of that are asserted, so the reframing cannot be dropped while the
    number stays."""
    rd = adj["summary"]["recall_is_label_contact_not_detection"]
    strict = adj["summary"]["openings_only"]

    assert rd["true_pairs"] == strict["true_pairs"]
    assert rd["missed"] == strict["fn"]
    # Every truth pair whose rooms share walkable floor was predicted: that is the construction
    # handing recall over, not a detection.
    assert rd["of_those_predicted"] == rd["pairs_whose_rooms_are_joined_by_walkable_floor"]
    # And the misses are exactly the pairs the raster severed, not pairs the code rejected.
    assert rd["missed_that_were_joined_by_walkable_floor"] == 0
    assert rd["true_pairs_the_width_filter_discarded"] == 0, (
        "if the width filter ever discards a real doorway, recall stops being pure construction "
        "and this sentence has to be rewritten rather than re-asserted")

    said = rd["what_it_means"]
    assert "NOT a detection rate" in said
    assert f"precision {strict['precision']}" in said

    for r in scored:
        d = r["recall_decomposition"]
        assert d["missed"] == r["openings_only"]["missed"]
        assert not d["true_pairs_discarded_as_a_whole_open_side"]


def test_a_no_skill_baseline_on_the_same_truth_is_published_and_beaten(adj, scored):
    """Without this the headline could be the annotation's geometry restated: two rooms that are
    close together on a drawn plan are usually joined. The baseline reads only the truth side and
    never runs openings(), so the gap between them is the part of the score that is ours."""
    base = adj["summary"]["no_skill_baseline"]
    loose = adj["summary"]["openings_only_all_pairs"]
    assert len(base["by_gap_m"]) >= 3, "one radius is a chosen point, not a baseline"
    for k, b in base["by_gap_m"].items():
        assert b["tp"] + b["fn"] == loose["true_pairs"], (
            f"baseline at d={k} is scored against a different truth set than the result it is "
            f"being compared with")
        assert b["f1"] == pytest.approx(2 * b["tp"] / (2 * b["tp"] + b["fp"] + b["fn"]), abs=1e-4)
        assert b["f1"] < loose["f1"], (
            f"a no-skill radius at d={k} matches or beats openings(); the headline would then be "
            f"measuring the annotation's geometry rather than the code")
    assert base["openings_f1_same_truth"] == loose["f1"]
    assert base["best_f1"] == max(b["f1"] for b in base["by_gap_m"].values())
    for r in scored:
        for k, b in r["no_skill_baseline"].items():
            assert b["tp"] + b["fn"] == r["openings_only_all_pairs"]["n_true"]


def test_the_door_population_is_published_as_a_distribution(adj, scored):
    """An earlier revision described these doors as "0.78-0.81 m wide" -- a 19% modal band
    presented as the population, used to explain why DOOR_MAX_M = 0.70 m fails. The conclusion
    survives on the ablation; the characterisation did not. The distribution is published
    instead, and summing the per-storey lists has to reproduce it."""
    from scanplan.geometry.rooms import DOOR_MAX_M
    w = adj["summary"]["annotated_door_widths"]
    widths = sorted(x for r in scored for x in r["door_width_m"])
    assert w["n"] == len(widths)
    assert w["min_m"] == widths[0]
    assert w["max_m"] == widths[-1]
    assert w["door_max_m"] == DOOR_MAX_M
    assert w["wider_than_door_max_m"] == sum(x > DOOR_MAX_M for x in widths)
    assert w["at_or_below_door_max_m"] == len(widths) - w["wider_than_door_max_m"]
    assert w["min_m"] < DOOR_MAX_M < w["max_m"], (
        "a single band would be a fair summary if the doors were in one; they are not")
    assert w["at_or_below_door_max_m"] > 0, (
        "the claim is that MOST doors are wider than the constant, not that all are")


def test_the_dataset_snapshot_is_pinned_in_the_artifact(adj):
    """The result file is regenerated and diffed byte for byte by clean_clone_check.sh, so an
    unpinned upstream re-upload would read as a DIFFERS in our code. The revision the committed
    file was generated from is named in both the fetcher and the artifact."""
    from scripts.fetch_houselayout3d import REPO, REVISION
    src = adj["dataset_source"]
    assert src["repo_id"] == REPO
    assert src["revision"] == REVISION
    assert len(REVISION) == 40 and all(c in "0123456789abcdef" for c in REVISION), (
        "a branch or tag name is not a pin")


def test_the_excuse_offered_for_the_false_positives_does_not_fire_on_the_true_ones(adj):
    """Most of the false positives are explained as openings the dataset draws but names no door
    on. An explanation that also covered the true positives would explain nothing."""
    fp = adj["false_positives"]
    assert fp["same_flag_on_the_true_positives"]["n"] == adj["summary"]["openings_only"]["tp"]
    assert fp["same_flag_on_the_true_positives"]["any"] == 0
    assert fp["meet_only_in_reveals_with_no_door_annotated"] <= fp["total"]


def test_the_scope_section_still_disclaims_the_pipeline_and_the_room_splitting(adj):
    """The number is about one function given perfect input. If that sentence ever leaves the
    file, the number starts reading as an end-to-end result."""
    text = " ".join(adj["scope"]["what_this_does_not_validate"]).lower()
    assert "end to end" in text
    assert "split_rooms" in text
    assert "does not excuse it" in text
    assert "recall as a detection rate" in text


def test_the_scope_prose_is_interpolated_from_the_run_and_not_written_as_literals(adj):
    """The defect this guards is one this repo has caught before in a docstring: the scope
    section used to carry "139 of 141", "recall 0.03", "0.78-0.81 m" and "60 of the 62" as
    string literals, so any rerun on a different snapshot would have shipped prose contradicting
    its own summary block -- and a keyword-matching test would not have noticed. The prose is now
    built from the computed values, which is checked here by requiring it to quote them."""
    text = json.dumps(adj["scope"])
    head = adj["summary"]["openings_only"]
    spl = adj["summary"]["with_splitter"]
    w = adj["summary"]["annotated_door_widths"]
    fp = adj["false_positives"]

    assert f"{head['tp']} of {head['true_pairs']} door pairs" in text
    assert f"recall {head['recall']} must not be read" in text
    assert f"precision {head['precision']}" in text
    assert f"recall {spl['recall']}, {spl['tp']} of {spl['true_pairs']} pairs" in text
    assert f"{w['n']} doors annotated here run {w['min_m']} to {w['max_m']} m" in text
    assert f"{w['at_or_below_door_max_m']} are at or below it" in text
    assert (f"{fp['meet_only_in_reveals_with_no_door_annotated']} of the {fp['total']} false "
            f"positives") in text

    # The two phrasings that were wrong rather than merely hardcoded: a 19% modal band sold as
    # the door population, and a with_splitter recall rounded in the direction that reads less
    # badly. The other three literals happen to be correct for this snapshot, which is exactly
    # why only the positive assertions above can tell whether they were computed.
    for stale in ("0.78-0.81", "recall 0.03 "):
        assert stale not in text, f"{stale!r} is back as a literal in the scope section"


def test_every_constant_in_the_construction_comes_from_our_side(adj):
    """Nothing about the raster may be taken from the truth. The cell size, the padding and the
    minimum room area are the pipeline's own; if one of them were tuned here it would be tuning
    against the answer."""
    from scanplan.geometry.rooms import ROOM_MIN_AREA_M2
    from scanplan.geometry.walls import CELL_M, MARGIN_M
    ours = adj["constants_from_our_side"]
    assert ours["cell_m"] == CELL_M
    assert ours["margin_m"] == MARGIN_M
    assert ours["room_min_area_m2"] == ROOM_MIN_AREA_M2
