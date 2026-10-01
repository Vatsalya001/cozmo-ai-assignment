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
# is printed every run. Three of them can never be recomputed from this commit:
#
#   fix_loop_before_gates.json  a snapshot of the code BEFORE the fix. Regenerating it from
#                               HEAD would produce the after-state and silently destroy the
#                               only record of what the fix changed.
#   fix_loop_after_gates.json   its pair, captured by the same harness at the same moment.
#                               Kept together so the comparison stays like-for-like.
#   head_to_head.json           needs tape-measured truth for the rooms in Part 4, which does
#                               not exist. The file records which inputs are missing.
#
# and one varies by design: timing.json is wall-clock seconds, a property of the machine.
set -uo pipefail
cd "$(dirname "$0")/.."
SRC="$PWD"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WITH_MODELS=0
[ "${1:-}" = "--with-models" ] && WITH_MODELS=1

# name | script | data it needs | why it is skipped (empty = it is run)
PLAN=(
  "gates.json|gates|supplied|"
  "depth_bias.json|depth_bias|arkitscenes_up|"
  "ceiling_vs_laser.json|ceiling_vs_laser|arkitscenes_up|"
  "arkitscenes_laser.json|arkitscenes_laser|arkitscenes|"
  "fix_loop_diagnosis.json|fix_loop_diagnosis|supplied|"
  "video_vs_lidar.json|video_vs_lidar|supplied|needs the models extra (torch + weights); pass --with-models"
  "photo_tier.json|photo_tier|supplied|needs the models extra (torch + weights); pass --with-models"
  "fix_loop_before_gates.json|-|-|snapshot of the code BEFORE the fix; not derivable from HEAD"
  "fix_loop_after_gates.json|-|-|its pair, captured by the same harness at the same moment"
  "head_to_head.json|-|-|needs tape-measured truth for Part 4, which does not exist"
  "timing.json|-|-|wall-clock seconds; a property of the machine, not of the pipeline"
)

echo "=== cloning into $TMP ==="
git clone -q "$SRC" "$TMP/repo" || { echo "clone failed"; exit 1; }
cd "$TMP/repo"

echo "=== linking the data a fresh clone cannot carry ==="
mkdir -p data
for d in supplied arkitscenes arkitscenes_up own; do
  if [ -e "$SRC/data/$d" ]; then
    ln -sfn "$(readlink -f "$SRC/data/$d")" "data/$d"
    echo "  data/$d"
  else
    echo "  data/$d ABSENT -- benchmarks needing it will be reported as not run"
  fi
done

EXTRA="dev"
[ "$WITH_MODELS" = 1 ] && EXTRA="dev,models"
echo "=== installing .[$EXTRA] ==="
python3 -m venv .venv >/dev/null 2>&1
./.venv/bin/pip install -q -e ".[$EXTRA]" >/dev/null 2>&1 || { echo "install failed"; exit 1; }

echo "=== tests ==="
./.venv/bin/pytest -q 2>&1 | tail -1

echo ""
echo "=== regenerating, then diffing committed against regenerated ==="
same=0; differ=0; failed=0; skipped=0
for row in "${PLAN[@]}"; do
  IFS='|' read -r name script needs why <<< "$row"

  if [ "$WITH_MODELS" = 1 ] && [[ "$why" == needs\ the\ models\ extra* ]]; then why=""; fi
  if [ -n "$why" ]; then
    printf '  %-12s %-28s %s\n' "SKIPPED" "$name" "$why"
    skipped=$((skipped+1)); continue
  fi
  if [ ! -e "data/$needs" ]; then
    printf '  %-12s %-28s %s\n' "SKIPPED" "$name" "data/$needs is not present on this machine"
    skipped=$((skipped+1)); continue
  fi

  rm -f "bench/results/$name"
  if ! ./.venv/bin/python "bench/$script.py" >/dev/null 2>&1 || [ ! -f "bench/results/$name" ]; then
    printf '  %-12s %-28s %s\n' "FAILED" "$name" "bench/$script.py did not produce it"
    failed=$((failed+1)); continue
  fi

  if ./.venv/bin/python - "$SRC/bench/results/$name" "bench/results/$name" <<'PY'
import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if 'runtime' not in k and 'wall_s' not in k}
    if isinstance(o, list): return [strip(x) for x in o]
    if isinstance(o, float): return round(o, 6)
    return o
sys.exit(0 if strip(a) == strip(b) else 1)
PY
  then printf '  %-12s %-28s %s\n' "REGENERATED" "$name" "matches the committed copy"; same=$((same+1))
  else printf '  %-12s %-28s %s\n' "DIFFERS" "$name" "committed copy does NOT match a fresh run"; differ=$((differ+1)); fi
done

echo ""
echo "$same regenerated and identical, $differ differ, $failed failed to run, $skipped not"
echo "regenerated (each with its reason above). Only the first number is evidence; a file that"
echo "was never recomputed cannot agree with anything."
[ "$differ" = 0 ] && [ "$failed" = 0 ]
