"""Head-to-head against magicplan, dimension by dimension.

Part 3 of the brief: two benchmark rooms, our output against one consumer scanning app on the
same rooms, error by dimension, beat or tie on at least 70% of shared dimensions.

Three inputs are needed and the script reports precisely which are missing rather than
silently comparing two of them:

  data/own/magicplan_results.md   the app's numbers      -- HAVE
  data/own/measurements.csv       tape ground truth      -- needed
  data/own/<capture>              our own capture        -- needed

A deviation to declare, not to hide: the brief specifies the LiDAR tier for this comparison.
The device available is an iPhone 16 base, which has no depth sensor, so our side runs at the
video tier. That is harder on us, not easier -- the video tier is measured at 26% to 69% from
the LiDAR reference, while magicplan's Corner Mode is a published 5-15 cm per wall.

    python bench/head_to_head.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
OWN = ROOT / "data" / "own"
OUT = ROOT / "bench" / "results" / "head_to_head.json"

# magicplan 2026.38.0, Manual-Scan Corner Mode, iPhone 16 base (no LiDAR).
# Transcribed from data/own/magicplan_results.md; the DXF is the authority for the geometry.
MAGICPLAN = {
    "R1": {
        "app": "magicplan", "version": "2026.38.0", "mode": "Manual-Scan Corner Mode",
        "left wall": 3.62, "right wall": 4.10, "bottom wall": 3.44,
        "top-left segment": 1.78, "notch depth": 0.49, "top-right segment": 1.66,
        "bottom door width": 0.77, "upper-right door width": 0.90,
        "ceiling height": 2.83, "floor area": 13.25, "perimeter": 13.41,
    },
    "R2": {
        "app": "magicplan", "version": "2026.38.0", "mode": "Manual-Scan Corner Mode",
        "ceiling height": 2.79, "floor area": 2.79, "perimeter": 5.91,
    },
}


def read_tape(path: Path) -> dict:
    """Tape ground truth, averaging the two readings per row."""
    if not path.is_file():
        return {}
    truth: dict[str, dict[str, float]] = {}
    with path.open() as f:
        for row in csv.DictReader(r for r in f if not r.lstrip().startswith("#")):
            room = (row.get("room") or "").strip()
            el = (row.get("element") or "").strip()
            if not room or not el:
                continue
            vals = [float(row[k]) for k in ("reading1_m", "reading2_m")
                    if row.get(k) and row[k].strip()]
            if not vals:
                continue
            truth.setdefault(room, {})[el] = sum(vals) / len(vals)
    return truth


def read_ours() -> dict:
    """Our pipeline's output for the same rooms, if a capture of them has been processed."""
    out = {}
    for d in sorted((ROOT / "out").glob("*")) if (ROOT / "out").is_dir() else []:
        j = d / "result.json"
        if not j.is_file():
            continue
        doc = json.loads(j.read_text())
        if "own" not in str(doc["capture"].get("source_path", "")):
            continue
        for room in doc["rooms"]:
            out[room["id"]] = {
                "floor area": room["floor_area_m2"]["value"],
                "ceiling height": room["ceiling_height_m"]["value"],
                "perimeter": room.get("perimeter_m", {}).get("value"),
                "_tier": doc["capture"]["tier"],
            }
    return out


def main() -> int:
    tape = read_tape(OWN / "measurements.csv")
    ours = read_ours()

    missing = []
    if not tape:
        missing.append("tape ground truth (data/own/measurements.csv) — the reference both "
                       "sides are scored against")
    if not ours:
        missing.append("our own output for these rooms (no capture of data/own has been "
                       "processed into out/)")

    rows = []
    for room, app_vals in MAGICPLAN.items():
        for dim, app_v in app_vals.items():
            if dim in ("app", "version", "mode"):
                continue
            truth_v = tape.get(room, {}).get(dim)
            our_v = (ours.get(room) or {}).get(dim)
            row = {"room": room, "dimension": dim, "magicplan_m": app_v,
                   "truth_m": truth_v, "ours_m": our_v}
            if truth_v is not None:
                row["magicplan_error_m"] = abs(app_v - truth_v)
                if our_v is not None:
                    row["our_error_m"] = abs(our_v - truth_v)
                    # "Beat or tie": ours is no worse than theirs, within 1 mm of measurement.
                    row["we_beat_or_tie"] = row["our_error_m"] <= row["magicplan_error_m"] + 0.001
            rows.append(row)

    scored = [r for r in rows if "we_beat_or_tie" in r]
    result = {
        "part": "Part 3 — head-to-head",
        "opponent": "magicplan 2026.38.0, Manual-Scan Corner Mode, iPhone 16 base (no LiDAR)",
        "declared_deviation":
            "The brief specifies the LiDAR tier for this comparison. The device available has "
            "no depth sensor, so our side runs at the video tier. This is harder on us, not "
            "easier: the video tier measures 26-69% from the LiDAR reference, while "
            "magicplan's Corner Mode is a published 5-15 cm per wall.",
        "rows": rows,
        "dimensions_total": len(rows),
        "dimensions_scored": len(scored),
        "missing_inputs": missing,
    }
    if scored:
        won = sum(r["we_beat_or_tie"] for r in scored)
        result["beat_or_tie"] = won
        result["beat_or_tie_pct"] = round(won / len(scored) * 100, 1)
        result["gate_met"] = won / len(scored) >= 0.70

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    print(f"magicplan dimensions recorded: {len(rows)}")
    if missing:
        print("\nCANNOT SCORE YET. Missing:")
        for m in missing:
            print(f"  - {m}")
        print("\nmagicplan's side is complete and committed; the table is built and will fill "
              "the moment the two inputs above exist.")
    else:
        print(f"\nscored {len(scored)} shared dimensions: beat or tie on "
              f"{result['beat_or_tie']} ({result['beat_or_tie_pct']}%)  "
              f"gate {'MET' if result['gate_met'] else 'NOT MET'} (target 70%)")
        for r in scored:
            mark = "ours" if r["we_beat_or_tie"] else "them"
            print(f"  {r['room']:<4} {r['dimension']:<24} truth {r['truth_m']:.3f}  "
                  f"ours {r['our_error_m']*1000:+6.0f} mm  magicplan "
                  f"{r['magicplan_error_m']*1000:+6.0f} mm   -> {mark}")

    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
