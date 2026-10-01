#!/usr/bin/env bash
# Reproduce every committed number from a FRESH CLONE, and diff against what is committed.
#
#   bash bench/clean_clone_check.sh
#
# The point is not that the code runs -- the test suite covers that. The point is that a
# reviewer who clones this repo and follows the README gets the numbers the documents claim.
# A result committed from a working tree that has drifted from the history is a number nobody
# else can obtain, which is worth less than no number at all.
set -uo pipefail
cd "$(dirname "$0")/.."
SRC="$PWD"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "=== cloning into $TMP ==="
git clone -q "$SRC" "$TMP/repo" || { echo "clone failed"; exit 1; }
cd "$TMP/repo"

echo "=== linking the data a fresh clone cannot carry ==="
mkdir -p data
for d in supplied arkitscenes_up; do
  [ -e "$SRC/data/$d" ] && ln -sfn "$(readlink -f "$SRC/data/$d")" "data/$d"
done

echo "=== installing ==="
python3 -m venv .venv >/dev/null 2>&1
./.venv/bin/pip install -q -e ".[dev]" >/dev/null 2>&1 || { echo "install failed"; exit 1; }

echo "=== tests ==="
./.venv/bin/pytest -q 2>&1 | tail -1

echo "=== regenerating benchmarks ==="
for b in depth_bias gates; do
  ./.venv/bin/python "bench/$b.py" >/dev/null 2>&1 && echo "  $b ok" || echo "  $b FAILED"
done

echo ""
echo "=== committed vs freshly regenerated ==="
same=0; diff_=0
for f in bench/results/*.json; do
  n="$(basename "$f")"
  if [ -f "$SRC/$f" ]; then
    if ./.venv/bin/python - "$SRC/$f" "$f" <<'PY'
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
    then echo "  identical  $n"; same=$((same+1))
    else echo "  DIFFERS    $n"; diff_=$((diff_+1)); fi
  fi
done
echo ""
echo "$same identical, $diff_ differ (runtime fields excluded -- they are wall-clock, not results)"
