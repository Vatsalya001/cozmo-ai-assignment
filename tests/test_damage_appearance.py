"""The appearance classifier is a BENCHMARK, not a shipped feature. These tests keep it that way.

`bench/damage_appearance.py` measures one thing: whether a building-defect class can be named
from a photograph using OpenCV colour/edge/texture statistics and a scikit-learn classifier. It
is easy to let a result like that quietly become three things it is not -- a satisfied gate, a
runtime capability, and a clean measurement. Each of those is guarded below.

Three properties are load-bearing and none of them is about the accuracy number:

1. **It beats the majority-class baseline.** An accuracy with no baseline beside it is not a
   result; 86% over six classes means nothing until you know that guessing "crack" every time
   scores 29%. The baseline is recomputed here from the published confusion matrix rather than
   trusted, because a baseline the benchmark reports about itself is exactly the number a
   benchmark has an incentive to get wrong.
2. **The leakage caveat is present and specific.** The split cannot be grouped by building, so
   the number is an upper bound. If that caveat is ever edited out, the result starts reading as
   a cross-building accuracy, which it is not.
3. **No weight file is committed.** The licence position (upstream BD3 states no licence) is
   only real if nothing derived from the images is in the repository. A `.pkl` appearing next to
   the result file would make the stated position false, and prose cannot detect that -- a
   filesystem check can.

These tests read the committed JSON. They never retrain: training needs the gitignored dataset
and ~2 minutes, and the whole point of committing the result is that the claim travels with the
code without the images.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "bench" / "results" / "damage_appearance.json"

# Model parameters fitted on licence-unknown images would be a derivative work of them.
WEIGHT_SUFFIXES = {".pkl", ".pickle", ".joblib", ".sav", ".pt", ".pth", ".onnx", ".h5",
                   ".pb", ".safetensors", ".ckpt", ".model", ".bin", ".npz", ".npy"}


@pytest.fixture(scope="module")
def dmg():
    assert RESULT.is_file(), "run bench/damage_appearance.py"
    return json.loads(RESULT.read_text())


# --------------------------------------------------------------- 1. it beats the baseline

def test_the_majority_class_baseline_is_recomputed_from_the_confusion_matrix(dmg):
    """The baseline is the number that makes the accuracy mean anything, so it is re-derived
    from the published per-class supports rather than taken on the benchmark's word."""
    cm = np.array(dmg["confusion_matrix"]["rows_are_true_cols_are_predicted"])
    support = cm.sum(axis=1)
    n = int(support.sum())
    assert n == dmg["split"]["test_images"], "the matrix must cover the whole held-out split"

    recomputed = float(support.max()) / n
    published = dmg["baseline_majority_class"]["binding"]["accuracy"]
    assert published == pytest.approx(recomputed, abs=5e-4), (
        f"published binding baseline {published} but the confusion matrix says {recomputed:.4f}")

    labels = dmg["confusion_matrix"]["labels"]
    assert labels[int(support.argmax())] == dmg["baseline_majority_class"]["binding"]["class"]


def test_the_overall_accuracy_is_the_trace_of_the_confusion_matrix(dmg):
    """Guards against the headline and the matrix drifting apart -- if they disagree, one of
    them was edited by hand and neither can be trusted."""
    cm = np.array(dmg["confusion_matrix"]["rows_are_true_cols_are_predicted"])
    assert dmg["accuracy_overall"] == pytest.approx(cm.trace() / cm.sum(), abs=5e-4)


def test_it_beats_the_majority_class_baseline(dmg):
    """The claim the benchmark exists to support. Compared against the MAPPED baseline, which
    is the harder of the two published bars because merging major_crack and minor_crack into
    one `crack` class makes the biggest class bigger."""
    acc = dmg["accuracy_overall"]
    base = dmg["baseline_majority_class"]["binding"]["accuracy"]
    raw_base = dmg["baseline_majority_class"]["raw_labels"]["accuracy"]

    assert base > raw_base, (
        "the mapped baseline must exceed the 7-label one; if it does not, the label mapping is "
        "not merging the two crack grades and the comparison is against the wrong bar")
    assert dmg["beats_baseline"] is True
    assert acc > base, f"accuracy {acc} does not beat the majority-class baseline {base}"
    # A margin this large is the result. A regression to within a few points of chance means
    # the features or the mapping broke, and the file should not keep claiming a capability.
    assert acc - base > 0.30, (
        f"accuracy {acc} is only {acc - base:.3f} above the {base} baseline; the committed "
        f"claim is a large margin, not a marginal one")


def test_every_class_is_predicted_better_than_its_own_prevalence(dmg):
    """Overall accuracy can hide a class the model never predicts. Recall above prevalence on
    EVERY class is what rules out 'it learned the three easy ones and shrugged'."""
    n = dmg["split"]["test_images"]
    weak = {c: (m["recall"], m["support"] / n) for c, m in dmg["per_class"].items()
            if m["recall"] <= m["support"] / n}
    assert not weak, f"classes at or below chance recall: {weak}"
    assert all(m["support"] > 0 for m in dmg["per_class"].values())


def test_the_reject_class_is_learnable_and_its_two_error_rates_are_distinguished(dmg):
    """`plain` is not a damage class -- it is the "nothing here" answer. A classifier that
    cannot decline would report damage on every clean wall, so this is the one class whose
    behaviour is reported on its own terms."""
    rej = dmg["reject_class_behaviour"]
    assert rej["plain_recall"] > 0.5, "the reject class must be genuinely learnable"
    # The two rates are different quantities and swapping them inverts the operational reading.
    assert rej["false_alarm_rate_on_plain"] == pytest.approx(1 - rej["plain_recall"], abs=5e-3)
    assert 0.0 <= rej["missed_damage_rate"] <= 1.0
    assert "clean walls called damaged" in rej["reading"]


# --------------------------------------------------------------- 2. the leakage caveat

def test_the_leakage_that_cannot_be_ruled_out_is_stated(dmg):
    """The caveat this file most needs to survive editing. Without it the 86% reads as a
    cross-building accuracy, which is not what was measured and not what the data can support."""
    caveat = dmg["split"]["leakage_cannot_be_ruled_out"].lower()
    assert "cannot" in caveat
    # The specific mechanism, not a vague gesture at "possible leakage".
    assert "building" in caveat and "defect" in caveat
    assert "no building id" in caveat
    assert "inflate" in caveat


def test_the_split_does_not_claim_to_be_grouped_or_clean(dmg):
    """A grouped split is the thing that would license a cross-building claim, and it is
    exactly what BD3's parquet makes impossible. Saying so is not optional."""
    split = dmg["split"]
    assert "publisher" in split["kind"].lower()
    blob = json.dumps(split).lower()

    # Banning the phrase outright would fail on the honest sentence "cannot be grouped by
    # building", so what is checked is that every mention of grouping or cleanliness sits in a
    # NEGATED sentence. An un-negated one would be the claim this project cannot support.
    # Sentence scope rather than a fixed character window, because the negation can be a long
    # way from the phrase ("a clean result here would NOT have been evidence of a clean split").
    negations = ("cannot", "not ", "never", "no ", "n't")
    for phrase in ("grouped by building", "clean split", "leakage-free"):
        for sentence in blob.split("."):
            if phrase in sentence:
                assert any(neg in sentence for neg in negations), (
                    f"the split section says '{phrase}' in a sentence that does not negate it "
                    f"('{sentence.strip()}'), which the data cannot demonstrate")
    for claim in dmg["what_this_does_not_close"]:
        if "grouped" in claim.lower():
            assert "upper bound" in claim.lower()
            break
    else:
        pytest.fail("what_this_does_not_close must say the number is an upper bound")


def test_the_duplicate_check_reports_what_it_found_and_admits_its_weakness(dmg):
    """MD5 across the split is the only leakage check the data permits, and it FOUND
    duplicates. Both halves matter: the measured effect, and the fact that a weak check finding
    anything means the split was never deduplicated at all."""
    chk = dmg["split"]["exact_duplicate_check"]
    assert "md5" in chk["method"].lower()
    assert chk["test_rows_affected"] >= 0
    assert "lower bound" in chk["why_this_is_weak"].lower()
    assert "re-encoding" in chk["why_this_is_weak"].lower()

    if chk["found"]:
        # The de-duplicated accuracy must still beat the baseline, or the headline rests on
        # the leaked rows and the result is an artefact.
        base = dmg["baseline_majority_class"]["binding"]["accuracy"]
        assert chk["accuracy_excluding_duplicate_test_rows"] > base
        assert chk["accuracy_excluding_duplicate_test_rows"] == pytest.approx(
            dmg["accuracy_overall"], abs=0.05), (
            "dropping byte-duplicates moved the accuracy by more than 5 points; the headline "
            "would then be mostly memorisation and should be restated")


# --------------------------------------------------------------- 3. nothing derived is shipped

def test_no_weight_file_is_committed_anywhere_in_the_repo(dmg):
    """The licence position is a claim about the filesystem, so it is checked against the
    filesystem. Upstream BD3 states no licence, so parameters fitted on its images are not
    committed -- and prose in a docstring cannot enforce that."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    offenders = [p for p in tracked if p and Path(p).suffix.lower() in WEIGHT_SUFFIXES]
    assert not offenders, (
        f"committed files that may carry model parameters: {offenders}. Weights fitted on "
        f"licence-unknown BD3 images are arguably a derivative work of them and must not be "
        f"committed; the benchmark trains at run time instead")

    assert dmg["licence_position"]["weights_shipped"] is False


def test_the_images_are_not_committed_and_the_dataset_path_is_gitignored(dmg):
    """The other half of the licence position: not redistributing the images."""
    import subprocess

    assert "gitignored" in dmg["dataset"]["local_path"]

    # The ignore RULE is asserted rather than `git check-ignore` on a concrete path: in an
    # agent worktree data/external is a symlink to the real dataset, and check-ignore refuses
    # to resolve "beyond a symbolic link". The rule plus an empty index is the durable check.
    ignore_rules = {line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()}
    assert "data/external/" in ignore_rules or "data/external" in ignore_rules, (
        "data/external must be gitignored; the BD3 images are licence-unknown and not ours "
        "to redistribute")

    tracked = subprocess.run(["git", "ls-files", "data/external"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    assert not tracked, f"files committed under data/external: {tracked}"


def test_the_licence_position_names_the_contradiction_it_rests_on(dmg):
    """The CC-BY-4.0 tag is the easy thing to rely on. The position only holds because the
    card's own prose defers upstream and upstream has no licence -- so that reasoning is
    recorded, not just the conclusion."""
    lic = dmg["licence_position"]
    assert lic["verdict"] == "licence-unknown"
    assert "cc-by-4.0" in lic["huggingface_tag"].lower()
    reasons = " ".join(lic["why_the_tag_does_not_hold"]).lower()
    assert "contradicts" in reasons
    assert "no licence" in reasons or "license: null" in reasons
    assert "github.com/praveenkottari/bd3-dataset" in reasons
    assert any("not redistributed" in c.lower() for c in lic["consequences_applied"])
    assert any("run time" in c.lower() for c in lic["consequences_applied"])


def test_sklearn_is_an_optional_extra_and_the_package_does_not_import_it(dmg):
    """The LiDAR tier must stay lean and offline. A benchmark dependency that leaked into the
    default install, or into scanplan/, would quietly make that false."""
    pyproject = (ROOT / "pyproject.toml").read_text()
    default_block = pyproject.split("[project.optional-dependencies]")[0]
    assert "scikit-learn" not in default_block, (
        "scikit-learn must not be a default dependency; it belongs to the [damage] extra")
    extras = pyproject.split("[project.optional-dependencies]")[1].split("[project.scripts]")[0]
    assert "damage = " in extras and "scikit-learn" in extras

    offenders = [p.relative_to(ROOT).as_posix() for p in (ROOT / "scanplan").rglob("*.py")
                 if "sklearn" in p.read_text() or "scikit" in p.read_text()]
    assert not offenders, f"scanplan/ must not reference sklearn: {offenders}"


# --------------------------------------------------------------- it is not a gate

def test_it_does_not_claim_to_satisfy_a_dmg_detect(dmg):
    """The failure mode this whole file guards: a classification benchmark being read as the
    staged-damage detection gate. It is not one, for two independent reasons, and both are
    recorded so that neither can be dropped quietly."""
    assert "NOT a gate result" in dmg["gate_status"]
    assert "A-DMG-DETECT is NOT satisfied" in dmg["gate_status"]

    blob = " ".join(dmg["what_this_does_not_close"]).lower()
    # Reason one: nothing was staged, so nothing was found.
    assert "a-dmg-detect" in blob and "not satisfied" in blob
    assert "no staged room" in blob
    # Reason two: the shipped detector is geometric and this transfers nothing to it.
    assert "geometric" in blob
    assert "wall plane" in blob
    # And it genuinely does not ship.
    assert "does not ship" in blob or "no runtime appearance classifier" in blob


def test_it_is_honest_about_classifying_pre_cropped_images(dmg):
    """Every BD3 image is already centred on its defect. Detection and localisation are the
    hard parts and neither is measured, which is the difference between this and the gate."""
    blob = " ".join(dmg["what_this_does_not_close"]).lower()
    assert "no detection" in blob and "no localisation" in blob
    assert "crop" in blob
    # No size means nothing can feed the schema's damage measurements.
    assert "width_m" in blob or "area_m2" in blob


def test_the_features_are_primitive_on_purpose_and_report_a_floor(dmg):
    """The number is a floor from colour/edge/texture statistics, not a ceiling. Reading it as
    'this is as good as appearance classification gets' would be wrong in the other direction."""
    feat = dmg["features"]
    assert set(feat["libraries"]) == {"opencv-python", "numpy"}
    assert "no torch" in feat["no_deep_features"]
    assert "floor" in feat["why_primitive"].lower() and "ceiling" in feat["why_primitive"].lower()
    assert feat["dimension"] == len(
        [n for group in feat["groups"] for n in [group]]) or feat["dimension"] > 100


def test_the_label_map_covers_bd3_and_lands_inside_the_schema_enum(dmg):
    """The mapping is what makes this benchmark about THIS project. If a BD3 label mapped to a
    class the output schema does not define, the result would be measuring someone else's
    taxonomy."""
    schema = json.loads((ROOT / "schema" / "output.schema.json").read_text())
    enum = set(schema["properties"]["damage"]["items"]["properties"]["class"]["enum"])

    mapping = dmg["dataset"]["label_map_to_schema_enum"]
    assert set(mapping) == set(dmg["dataset"]["raw_labels"]), (
        "every BD3 label present in the data must be mapped, and no others")

    damage_targets = {v for k, v in mapping.items() if v != "plain"}
    assert damage_targets <= enum, f"maps outside the schema enum: {damage_targets - enum}"
    assert damage_targets == {"crack", "water_stain", "mould", "peeling_paint", "hole"}
    # The two crack grades must collapse: the schema has one `crack`, not two.
    assert mapping["major_crack"] == mapping["minor_crack"] == "crack"
    # `plain` must NOT be smuggled in as a damage class.
    assert "plain" not in enum
    assert "not a damage class" in dmg["dataset"]["negative_class"]

    predicted = set(dmg["confusion_matrix"]["labels"])
    assert predicted == damage_targets | {"plain"}


def test_the_result_is_reproducible_from_the_committed_command(dmg):
    """The benchmark trains at run time, so the result is only checkable if the command that
    produced it is recorded and the run is seeded."""
    assert "fetch_bd3.py" in dmg["reproduce"] and "damage_appearance.py" in dmg["reproduce"]
    assert (ROOT / "scripts" / "fetch_bd3.py").is_file()
    assert (ROOT / "bench" / "damage_appearance.py").is_file()
    assert dmg["model"]["seed"] == 0
    assert "timing" in dmg["model"]["determinism"], (
        "the determinism claim must name wall-clock timing as its one exception, or it "
        "overstates itself")


def test_the_model_was_chosen_before_the_test_split_was_touched(dmg):
    """Picking the better of two models by their test accuracy is the oldest way to inflate a
    reported number. The choice is made on a slice of TRAIN and both candidates' validation
    scores are published so the choice can be audited."""
    model = dmg["model"]
    val = model["inner_validation_accuracy"]
    assert len(val) >= 2, "publishing one candidate's score proves nothing about the choice"
    assert model["chosen"] in val
    assert val[model["chosen"]] == max(val.values()), (
        f"{model['chosen']} was chosen but did not win inner validation: {val}")
    assert "TRAIN" in model["selection"] and "before the test split" in model["selection"]


# --------------------------------------------------------- the guards that were missing

def test_the_three_damage_row_rates_partition_the_damage_rows(dmg):
    """Every other figure in `reject_class_behaviour` is re-derived from the confusion matrix
    by a test. This one was not, and it was wrong: the wrong-class share was published as
    `1 - accuracy_on_damage_rows_only`, which is TOTAL damage-row error and double-counts the
    rows the same sentence itemises as called-clean. 15.5% where the truth is 15.2%.

    A damage row has exactly three possible outcomes -- right class, called clean, wrong damage
    class -- so the three rates must sum to 1 and each must be recomputable from the matrix.
    """
    rej = dmg["reject_class_behaviour"]
    cm = np.asarray(dmg["confusion_matrix"]["rows_are_true_cols_are_predicted"], dtype=float)
    labels = dmg["confusion_matrix"]["labels"]
    neg = labels.index("plain")

    damage = [i for i in range(len(labels)) if i != neg]
    n_damage = cm[damage].sum()
    right = sum(cm[i, i] for i in damage)
    called_clean = sum(cm[i, neg] for i in damage)
    wrong_class = n_damage - right - called_clean

    assert n_damage > 0
    assert rej["accuracy_on_damage_rows_only"] == pytest.approx(right / n_damage, abs=5e-5)
    assert rej["missed_damage_rate"] == pytest.approx(called_clean / n_damage, abs=5e-5)
    assert rej["wrong_damage_class_rate"] == pytest.approx(wrong_class / n_damage, abs=5e-5)

    # The partition itself: this is the assertion whose absence let the double-count ship.
    total = (rej["accuracy_on_damage_rows_only"] + rej["missed_damage_rate"]
             + rej["wrong_damage_class_rate"])
    assert total == pytest.approx(1.0, abs=3e-4), (
        f"the three damage-row rates must partition the damage rows, got {total}")

    # And the prose must quote the residual, not total damage-row error.
    assert f"{rej['wrong_damage_class_rate']:.1%}" in rej["reading"]
    assert f"{1 - rej['accuracy_on_damage_rows_only']:.1%}" not in rej["reading"], (
        "the reading quotes 1 - accuracy_on_damage_rows_only, which double-counts the "
        "called-clean rows it itemises separately")


def test_the_module_docstring_repeats_no_unchecked_accuracy_literal(dmg):
    """The de-duplicated accuracy was hardcoded in the docstring as 0.8623 -- a value the
    793-row test split cannot produce (x773 is not an integer) and 0.2 points FLATTERING.
    Eighteen tests and eight mutation attempts passed with it wrong, because no test read the
    docstring. The literal is gone and the docstring points at the JSON field instead; this
    test fails if any accuracy literal comes back without a check behind it."""
    import re

    doc = (ROOT / "bench" / "damage_appearance.py").read_text().split('"""')[1]
    dup = dmg["split"]["exact_duplicate_check"]
    computed = {
        f"{dmg['accuracy_overall']:.4f}",
        f"{dup['accuracy_excluding_duplicate_test_rows']:.4f}",
    }
    for literal in re.findall(r"0\.\d{3,4}", doc):
        assert literal in computed, (
            f"the docstring hardcodes {literal}, which is not a figure this run computed. "
            f"Either delete it and point at the result JSON, or add a test that pins it.")

    # The pointer must actually be there, so deleting the number did not delete the signpost.
    assert "accuracy_excluding_duplicate_test_rows" in doc


def test_the_result_file_is_in_the_reproduction_bundle(dmg):
    """A committed result file outside bench/clean_clone_check.sh's PLAN made three separate
    claims false at once -- the technical report's "classifies every result file", the README's
    file count, and compliance matrix D.4's "regenerates every reported number". The PLAN row
    may say the file cannot be regenerated from a clone, but it must exist and name the
    commands, and the script must refuse to run on a result file it does not classify."""
    check = (ROOT / "bench" / "clean_clone_check.sh").read_text()
    assert "damage_appearance.json|" in check, (
        "damage_appearance.json has no row in clean_clone_check.sh's PLAN")
    row = next(ln for ln in check.splitlines() if "damage_appearance.json|" in ln)
    assert "fetch_bd3.py" in row and "damage_appearance.py" in row, (
        "the PLAN row must name the two commands that regenerate the file")

    # The completeness assert, and its wiring. A hand-maintained list has drifted twice.
    assert "plan_covers_every_result_file" in check
    assert check.count("plan_covers_every_result_file") >= 2, (
        "the completeness check is defined but never called")
    assert "PLAN IS INCOMPLETE" in check

    # Every committed result file is classified -- the same invariant the script enforces.
    listed = {ln.strip().strip('"').split("|")[0]
              for ln in check.split("PLAN=(")[1].split("\n)")[0].splitlines() if "|" in ln}
    on_disk = {p.name for p in (ROOT / "bench" / "results").glob("*.json")}
    assert not (on_disk - listed), f"result files missing from PLAN: {sorted(on_disk - listed)}"

    # And reproduce.sh runs it rather than omitting it, guarded on the gitignored input.
    repro = (ROOT / "bench" / "reproduce.sh").read_text()
    assert "damage_appearance.py" in repro and "fetch_bd3.py" in repro


def test_the_timing_block_says_which_figures_are_measured(dmg):
    """`feature_extraction_cold_s` was a hardcoded 80.0 beside a note calling it "a measured
    full pass", and `total_s` was a WARM run -- so the block published a total SMALLER than the
    cold figure sitting next to it. Each figure must now declare which kind of run it is."""
    t = dmg["timing"]
    assert isinstance(t["run_was_cold"], bool)
    assert t["total_s_kind"] == ("cold" if t["run_was_cold"] else "warm")
    assert "ESTIMATE" in t["feature_extraction_note"]
    assert "feature_extraction_cold_estimate_s" in t
    assert "feature_extraction_cold_s" not in t, (
        "the unqualified name claimed a measurement the writing run does not make")
    # A warm total can no longer sit next to a larger cold figure with nothing distinguishing
    # them: the cold total is published too, and it is never smaller than the warm one.
    assert t["cold_total_estimate_s"] >= t["total_s"] - 1e-6
    if not t["run_was_cold"]:
        assert t["cold_total_estimate_s"] > t["total_s"]


def test_one_run_gets_one_characterisation_of_its_fit_time(dmg):
    """"trained in seconds" sat in what_this_closes beside fit_s = 35.16 and a ~2 min
    end-to-end cold total: one number, three characterisations, in one artifact."""
    closes = dmg["what_this_closes"]
    assert "trained in seconds" not in closes
    assert f"~{dmg['timing']['fit_s']:.0f} s to fit" in closes, (
        "the fit time in the prose must be formatted from timing.fit_s, not restated")
    assert f"~{dmg['timing']['cold_total_estimate_s'] / 60:.1f} min end to end cold" in closes


def test_the_leakage_narrowing_travels_to_the_skim_surfaces(dmg):
    """The gate disclaimer reached the README row and the `answer` field; the leakage caveat
    did not. That omission was selective, not accidental -- the two caveats are the same kind
    of narrowing and 86.4% is unreadable without the second one."""
    dup = dmg["split"]["exact_duplicate_check"]
    dedup = dup["accuracy_excluding_duplicate_test_rows"]

    answer = dmg["answer"]
    assert "UPPER BOUND" in answer
    assert "building" in answer
    assert f"{dup['test_rows_affected']} of {dmg['split']['test_images']}" in answer
    assert f"{dedup:.1%}" in answer

    readme = (ROOT / "README.md").read_text()
    row = next((ln for ln in readme.splitlines()
                if "bench/damage_appearance.py" in ln and ln.startswith("|")), None)
    assert row, "bench/damage_appearance.py has no README row"
    assert "upper bound" in row.lower() and "cross-building" in row.lower()
    assert "A-DMG-DETECT" in row, "the gate disclaimer must not be dropped either"
    # Pinned to the computed fields, so the docstring defect cannot recur in the README.
    assert f"{dmg['accuracy_overall']:.1%}" in row
    assert f"{dedup:.1%}" in row
    assert f"{dup['test_rows_affected']} of {dmg['split']['test_images']}" in row


def test_the_optional_extra_declares_a_parquet_engine_and_fails_before_the_download(dmg):
    """pyarrow was undeclared. pandas does not pull a parquet engine, nothing in this project
    pulled one transitively, and BOTH documented commands died on "Unable to find a usable
    engine" after a clean install -- fetch_bd3.py only AFTER its ~800 MB download, because the
    summary step ran last. Declared, and checked before the first byte."""
    pyproject = (ROOT / "pyproject.toml").read_text()
    extras = pyproject.split("[project.optional-dependencies]")[1].split("[project.scripts]")[0]
    damage_line = next(ln for ln in extras.splitlines() if ln.startswith("damage = "))
    assert "pyarrow" in damage_line, "pandas.read_parquet has no engine without it"
    assert "scikit-learn" in damage_line

    fetch = (ROOT / "scripts" / "fetch_bd3.py").read_text()
    assert "both are already deps" not in fetch, "that claim was false"
    # The engine check must precede the download loop, or the reviewer pays 800 MB to learn it.
    assert fetch.index("    require_parquet_engine()") < fetch.index('download(f"{BASE}/{name}"'), (
        "the parquet-engine check must run BEFORE the download loop")

    bench = (ROOT / "bench" / "damage_appearance.py").read_text()
    assert bench.index("    _require_extra()") < bench.index("from sklearn.ensemble"), (
        "the extra must be checked before the ~80 s cold feature pass, not after it")


def test_a_missing_damage_extra_names_the_install_command(dmg):
    """Following the README used to give a bare ModuleNotFoundError -- a defect class this repo
    has already logged and fixed once for the models extra. Both entry points must name the
    command, and the README must document it next to the .[dev] line."""
    for path in (ROOT / "bench" / "damage_appearance.py", ROOT / "scripts" / "fetch_bd3.py"):
        src = path.read_text()
        assert "SystemExit" in src
        assert ".[damage]" in src, f"{path.name} must name the install command it needs"

    readme = (ROOT / "README.md").read_text()
    install = readme.split("## Install and run")[1].split("### One command per capture")[0]
    assert 'pip install -e ".[damage]"' in install, (
        "the [damage] extra must be documented beside the .[dev] instruction, not only in a "
        "benchmark table row")


def test_the_declined_changes_page_records_the_reversal(dmg):
    """Section 3 declined building an appearance classifier as the project's position, and the
    tree now contains one. That was the only self-contradiction in the submission. Section 2 is
    the house style for a declined change that later half-shipped: amend in place, record the
    reversal, say which half of the objection still stands."""
    page = (ROOT / "docs" / "declined_changes.md").read_text()
    section = page.split("## 3. Public defect data")[1].split("\n## 4.")[0]
    # Markdown hard-wraps at 100 columns, so match on unwrapped prose.
    flat = " ".join(section.split())

    # The reversal is recorded, not quietly deleted.
    assert "DECLINED as a gate validation" in flat
    assert "stands" in flat and "wrong" in flat
    # The objection that still stands, and the fact that nothing calls it a validation.
    assert "cannot validate the geometric detector" in flat
    assert "NOT a gate result" in flat
    assert "NOT BUILT" in flat
    # The sentence that was wrong is quoted rather than silently dropped.
    assert "adding a capability and calling it a validation" in flat
    # And the narrowing travels here too.
    assert "upper bound" in flat.lower()
    assert f"{dmg['accuracy_overall']:.1%}" in flat
