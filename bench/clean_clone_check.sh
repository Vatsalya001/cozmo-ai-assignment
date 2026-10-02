#!/usr/bin/env bash
# Reproduce every committed number from a FRESH CLONE, and diff against what is committed.
#
#   bash bench/clean_clone_check.sh                 # everything the default install can do
#   bash bench/clean_clone_check.sh --with-models   # also the two tiers that need torch
#
# The point is not that the code runs -- the test suite covers that. The point is that a
# reviewer who clones this repo and follows the README gets the numbers the documents claim.
# A result committed from a working tree that has drifted from the history is a number nobody
# else can obtain, which is worth less than no number at all.
#
# ## Why this script names what it did NOT regenerate
#
# The first version of this check regenerated two benchmarks and then diffed all nine result
# files, reporting "8 identical". Seven of those were identical because the clone had copied
# them and nothing had touched them since -- the diff was comparing a file with itself. That
# is a pass that cannot fail, which is worse than no check, because it reads like evidence.
#
# So each result file is now classified. REGENERATED means the clone recomputed it from the
# captures and the committed copy matched. SKIPPED means it was not recomputed, and the reason
# is printed every run. Two of them can never be recomputed from this commit:
#
#   fix_loop_before_gates.json  a snapshot of the code BEFORE the fix. Regenerating it from
#                               HEAD would produce the after-state and silently destroy the
#                               only record of what the fix changed.
#   fix_loop_after_gates.json   its pair, captured by the same harness at the same moment.
#                               Kept together so the comparison stays like-for-like.
#
# one varies by design: timing.json is wall-clock seconds, a property of the machine.
#
# and one needs inputs a clone cannot have: damage_appearance.json is the BD3 appearance
# benchmark, which needs the optional [damage] extra and a gitignored ~800 MB image fetch whose
# licence position forbids redistributing it. The row names the two commands that regenerate it.
#
# head_to_head.json IS regenerated, although the comparison it describes cannot be scored yet.
# The artifact is deterministic without its missing inputs -- magicplan's side plus a precise
# statement of what is absent -- so there is no reason to exempt it, and regenerating it proves
# the "missing inputs" list is current rather than a stale note someone wrote once.
set -uo pipefail
cd "$(dirname "$0")/.."
SRC="$PWD"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WITH_MODELS=0
[ "${1:-}" = "--with-models" ] && WITH_MODELS=1

# name | script [args] | data it needs | why it is skipped (empty = it is run)
PLAN=(
  "gates.json|gates|supplied|"
  "depth_bias.json|depth_bias|arkitscenes_up|"
  "ceiling_vs_laser.json|ceiling_vs_laser|arkitscenes_up|"
  "arkitscenes_laser.json|arkitscenes_laser|arkitscenes|"
  "fix_loop_diagnosis.json|fix_loop_diagnosis|supplied|"
  "same_flat.json|same_flat|supplied|"
  "ceiling_walks.json|ceiling_walks|arkitscenes_walks|"
  "ceiling_walks_uncorrected.json|ceiling_walks --no-bias-correction|arkitscenes_walks|"
  "wall_distance_walks.json|wall_distance_walks|arkitscenes_walks|"
  "head_to_head.json|head_to_head|own|"
  "head_to_head_engineer.json|head_to_head_engineer|supplied|"
  "houselayout_adjacency.json|houselayout_adjacency|external/houselayout3d|"
  "video_vs_lidar.json|video_vs_lidar|supplied|needs the models extra (torch + weights); pass --with-models"
  "photo_tier.json|photo_tier|supplied|needs the models extra (torch + weights); pass --with-models"
  "photo_vs_lidar.json|photo_vs_lidar|supplied|needs the models extra (torch + weights); pass --with-models"
  "fix_loop_before_gates.json|-|-|snapshot of the code BEFORE the fix; not derivable from HEAD"
  "fix_loop_after_gates.json|-|-|its pair, captured by the same harness at the same moment"
  "timing.json|-|-|wall-clock seconds; a property of the machine, not of the pipeline"
  "damage_appearance.json|-|-|needs the [damage] extra and the gitignored ~800 MB BD3 fetch; run: python scripts/fetch_bd3.py && python bench/damage_appearance.py"
)

# ## Why the list above is now CHECKED against the directory
#
# PLAN is hand-maintained, and it has drifted twice. `ceiling_walks_uncorrected.json` was
# written by an ablation flag nobody added a row for, and `damage_appearance.json` arrived
# later and was added to neither this list nor bench/reproduce.sh. The symptom was a summary
# line that added up -- "13 regenerated, 3 not regenerated" -- while the directory held 17
# tracked result files. A count that is internally consistent and still short is worse than a
# visibly wrong one, because it reads as a complete accounting.
#
# So the list is no longer trusted: every *.json in bench/results/ must appear in PLAN, and an
# unlisted one FAILS the check rather than being silently passed over. Adding a result file now
# forces a decision about whether a fresh clone can regenerate it.
plan_covers_every_result_file () {
  local listed missing=() f
  listed="$(printf '%s\n' "${PLAN[@]}" | cut -d'|' -f1)"
  for f in "$SRC"/bench/results/*.json; do
    [ -e "$f" ] || continue
    grep -qxF "$(basename "$f")" <<< "$listed" || missing+=("$(basename "$f")")
  done
  if [ "${#missing[@]}" -ne 0 ]; then
    echo "  PLAN IS INCOMPLETE: bench/results/ holds files this script does not classify:"
    printf '    %s\n' "${missing[@]}"
    echo "  Add a PLAN row for each (script name, or '-' plus the reason it cannot be"
    echo "  regenerated from a fresh clone). Every committed result file must be accounted for."
    return 1
  fi
  echo "  PLAN classifies all $(ls -1 "$SRC"/bench/results/*.json | wc -l) committed result files"
}

# Show what pip actually said. The first version discarded stderr and printed "install failed",
# which turned a one-line pip diagnostic into a debugging session.
pip_or_die () {
  local log="$TMP/pip.log"
  if ! "$@" >"$log" 2>&1; then
    echo "  INSTALL FAILED: $*"
    echo "  --- last 15 lines of pip output ---"
    tail -15 "$log" | sed 's/^/  /'
    exit 1
  fi
}

echo "=== cloning into $TMP ==="
git clone -q "$SRC" "$TMP/repo" || { echo "clone failed"; exit 1; }
cd "$TMP/repo"

echo "=== linking the data a fresh clone cannot carry ==="
mkdir -p data
# data/own is NOT linked. Its magicplan exports are tracked, so `git clone` already created
# the directory -- and `ln -sfn target data/own` then puts the link INSIDE it as data/own/own,
# silently leaving the tracked copy in place. That trap hid a real difference: the committed
# head_to_head.json had been generated from a filled measurements sheet that is gitignored, so
# a reviewer's clone produced a different file. Reading the tracked template is CORRECT here,
# so the directory is left exactly as the clone made it.
for d in supplied arkitscenes arkitscenes_up arkitscenes_walks external; do
  if [ -e "$SRC/data/$d" ]; then
    rm -rf "data/$d"
    ln -sfn "$(readlink -f "$SRC/data/$d")" "data/$d"
    echo "  data/$d"
  else
    echo "  data/$d ABSENT -- benchmarks needing it will be reported as not run"
  fi
done

echo "=== installing ==="
python3 -m venv .venv >/dev/null 2>&1
if [ "$WITH_MODELS" = 1 ]; then
  # CPU torch from PyTorch's own index, exactly as the README instructs. The default PyPI
  # wheel on Linux is the CUDA build: several GB, for a pipeline that runs on CPU throughout.
  echo "  .[dev,models] with CPU torch (large download, first run only)"
  # --no-cache-dir: a download interrupted partway leaves a corrupt entry in pip's HTTP cache,
  # and every later run then fails a hash check with a message about tampering. That happened
  # here, cost real time to diagnose, and has nothing to do with this repo.
  pip_or_die ./.venv/bin/pip install -q --no-cache-dir \
      "torch>=2.4,<2.10" "torchvision>=0.19,<0.25" \
      --index-url https://download.pytorch.org/whl/cpu
  pip_or_die ./.venv/bin/pip install -q -e ".[dev,models]"
else
  echo "  .[dev] -- no weights, no network; pass --with-models to include the model tiers"
  pip_or_die ./.venv/bin/pip install -q -e ".[dev]"
fi

echo "=== tests ==="
# Name the failures. `tail -1` printed "1 failed, 142 passed" and hid WHICH test, which made a
# clone-only failure invisible -- exactly the case this check exists to surface.
./.venv/bin/pytest -q 2>&1 | tail -1
./.venv/bin/pytest -q 2>&1 | grep -E '^(FAILED|ERROR)' | sed 's/^/  /' || true

echo ""
echo "=== checking the plan is complete before trusting its counts ==="
plan_covers_every_result_file || exit 1

echo ""
echo "=== regenerating, then diffing committed against regenerated ==="
same=0; differ=0; failed=0; skipped=0
for row in "${PLAN[@]}"; do
  IFS='|' read -r name script needs why <<< "$row"
  # The script field may carry arguments: ceiling_walks.py writes a SECOND result file under
  # --no-bias-correction, and that file is committed, so it needs its own row.
  read -r -a cmd <<< "$script"
  script="${cmd[0]}"
  script_args=("${cmd[@]:1}")

  if [ "$WITH_MODELS" = 1 ] && [[ "$why" == needs\ the\ models\ extra* ]]; then why=""; fi
  if [ -n "$why" ]; then
    printf '  %-12s %-30s %s\n' "SKIPPED" "$name" "$why"
    skipped=$((skipped+1)); continue
  fi
  if [ "$needs" != "-" ] && [ ! -e "data/$needs" ]; then
    printf '  %-12s %-30s %s\n' "SKIPPED" "$name" "data/$needs is not present on this machine"
    skipped=$((skipped+1)); continue
  fi

  rm -f "bench/results/$name"
  if ! ./.venv/bin/python "bench/$script.py" "${script_args[@]+"${script_args[@]}"}" \
       >/dev/null 2>&1 || [ ! -f "bench/results/$name" ]; then
    printf '  %-12s %-30s %s\n' "FAILED" "$name" "bench/$script.py ${script_args[*]-} did not produce it"
    failed=$((failed+1)); continue
  fi

  if ./.venv/bin/python - "$SRC/bench/results/$name" "bench/results/$name" <<'PY'
import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
def strip(o):
    # A-RUNTIME is the one row whose STATUS legitimately depends on machine state: under CPU
    # contention it reports NOT MEASURED rather than scoring a wall-clock that is not the
    # pipeline's. That is deliberate, and it means this row cannot be byte-reproducible. It is
    # excluded here for the same reason the runtime fields are, and for no other row.
    if isinstance(o, dict):
        if o.get('gate') == 'A-RUNTIME':
            return {'gate': 'A-RUNTIME', 'target': o.get('target')}
        return {k: strip(v) for k, v in o.items() if 'runtime' not in k and 'wall_s' not in k}
    if isinstance(o, list): return [strip(x) for x in o]
    if isinstance(o, float): return round(o, 6)
    return o
sys.exit(0 if strip(a) == strip(b) else 1)
PY
  then printf '  %-12s %-30s %s\n' "REGENERATED" "$name" "matches the committed copy"; same=$((same+1))
  else printf '  %-12s %-30s %s\n' "DIFFERS" "$name" "committed copy does NOT match a fresh run"; differ=$((differ+1)); fi
done

echo ""
echo "$same regenerated and identical, $differ differ, $failed failed to run, $skipped not"
echo "regenerated (each with its reason above). Only the first number is evidence; a file that"
echo "was never recomputed cannot agree with anything."
[ "$differ" = 0 ] && [ "$failed" = 0 ]
