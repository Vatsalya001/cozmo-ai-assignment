#!/usr/bin/env bash
# Regenerate every reported number from raw inputs.
#
#   bash bench/reproduce.sh
#
# Expects the supplied captures at data/supplied (a symlink is fine) and, for the laser
# calibration, ARKitScenes under data/arkitscenes. Both are fetched, not committed.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
fail=0

step () {
  echo ""
  echo "=== $1 ==="
  shift
  "$@" || { echo "  FAILED"; fail=1; }
}

step "input integrity (captures must not have changed)" \
     "$PY" scripts/capture_manifest.py data/supplied --check
step "unit and accuracy tests" .venv/bin/pytest -q
step "gates across every supplied capture" "$PY" bench/gates.py
step "fix-loop diagnosis (evidence behind the declaration)" "$PY" bench/fix_loop_diagnosis.py
step "depth bias measured per-pixel against FARO laser truth" "$PY" bench/depth_bias.py
step "storey-height calibration (reports NOT MEASURED; see the script header)" "$PY" bench/arkitscenes_laser.py
step "video tier against the LiDAR reference, and interval calibration" "$PY" bench/video_vs_lidar.py
step "photo tier room boxes and stitch grouping" "$PY" bench/photo_tier.py
step "head-to-head vs magicplan" "$PY" bench/head_to_head.py
step "sync the compliance matrix gate table to the regenerated gates" \
     "$PY" scripts/sync_compliance_matrix.py

echo ""
echo "results in bench/results/:"
ls -1 bench/results/ 2>/dev/null | sed 's/^/  /'
echo ""
[ "$fail" -eq 0 ] && echo "all steps completed" || echo "one or more steps failed (exit 1)"
exit "$fail"
