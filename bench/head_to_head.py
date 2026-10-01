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


# Dimensions that match by name on both sides, with no interpretation required.
DIRECT = ("floor area", "ceiling height", "perimeter")


def read_ours(out_dir: Path | None = None) -> dict:
    """Our pipeline's output for the same rooms, if a capture of them has been processed.

    Wall lengths and opening widths are carried through as *sorted lists*, not as named
    dimensions. They cannot be named: our wall IDs are positional (R1.W1, R1.W2, ...) and
    assigned by the order the polygon was traced, while magicplan's are human labels like
    "left wall". Nothing in either output says which of ours is theirs.
    """
    out = {}
    base = out_dir if out_dir is not None else (ROOT / "out")
    for d in sorted(base.glob("*")) if base.is_dir() else []:
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
                "_walls": sorted((w["length_m"]["value"] for w in room.get("walls", [])),
                                 reverse=True),
                "_openings": sorted((o["width_m"]["value"] for o in room.get("openings", [])),
                                    reverse=True),
                "_tier": doc["capture"]["tier"],
            }
    return out


def pair_by_rank(theirs: dict, ours: list[float]) -> dict[str, float | None]:
    """Match unlabelled quantities by rank: longest to longest, second to second.

    ## Why rank, and why not "closest"

    Our wall IDs are positional and magicplan's are human labels, so there is no correspondence
    in the data. Two ways to invent one:

    - **Closest match** — for each of their dimensions, take whichever of ours is nearest. This
      is what a benchmark that wants to win does. It cannot lose: every dimension is scored
      against our most flattering wall, and a pipeline that emitted random lengths would still
      post respectable errors.
    - **Rank** — sort both sides by length and pair them off. Symmetric, uses each of our walls
      exactly once, and can be badly wrong in a way that shows up as a bad score rather than
      hiding in it.

    Rank is used. It is only valid when both sides report the same number of walls, which is
    checked by the caller: pairing 4 of ours against 6 of theirs would be comparing a room to a
    different room.
    """
    names = sorted(theirs, key=lambda n: -theirs[n])
    return {name: ours[i] for i, name in enumerate(names)}


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
        mine = ours.get(room) or {}
        dims = {k: v for k, v in app_vals.items() if k not in ("app", "version", "mode")}

        # Build the correspondence for the unlabelled quantities once per room.
        walls = {k: v for k, v in dims.items() if "wall" in k or "segment" in k or "notch" in k}
        doors = {k: v for k, v in dims.items() if "door" in k}
        paired: dict[str, float | None] = {}
        notes: dict[str, str] = {}
        for group, key, label in ((walls, "_walls", "wall"), (doors, "_openings", "opening")):
            if not group:
                continue
            got = mine.get(key)
            if got is None:
                continue                              # no output of ours at all; handled below
            if len(got) != len(group):
                for n in group:
                    notes[n] = (f"not scorable: magicplan reports {len(group)} {label} "
                                f"dimensions for {room} and we report {len(got)}. Pairing "
                                f"unequal counts by rank would compare different geometry")
                continue
            paired.update(pair_by_rank(group, got))
            for n in group:
                notes[n] = f"paired by rank among the {len(got)} {label} lengths"

        for dim, app_v in dims.items():
            truth_v = tape.get(room, {}).get(dim)
            our_v = mine.get(dim) if dim in DIRECT else paired.get(dim)
            row = {"room": room, "dimension": dim, "magicplan_m": app_v,
                   "truth_m": truth_v, "ours_m": our_v}
            if dim in notes:
                row["correspondence"] = notes[dim]
            elif dim in DIRECT:
                row["correspondence"] = "matched by name; no interpretation needed"

            if truth_v is None:
                row["not_scored_because"] = "no tape truth for this dimension"
            elif our_v is None:
                row["not_scored_because"] = (
                    notes.get(dim) or "our pipeline produced no value for this dimension")
            else:
                row["magicplan_error_m"] = abs(app_v - truth_v)
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
        "correspondence_method":
            "floor area, ceiling height and perimeter match by name. Wall lengths and opening "
            "widths have no correspondence in the data -- our IDs are positional, magicplan's "
            "are human labels -- so they are paired by RANK among sorted lengths, and only when "
            "both sides report the same count. Pairing each of theirs to whichever of ours is "
            "nearest would be the flattering choice and was rejected: it cannot lose.",
        "rows": rows,
        "dimensions_total": len(rows),
        "dimensions_scored": len(scored),
        "dimensions_not_scored": len(rows) - len(scored),
        "why_not_scored": sorted({r["not_scored_because"] for r in rows
                                  if "not_scored_because" in r}),
        "missing_inputs": missing,
    }
    if scored:
        won = sum(r["we_beat_or_tie"] for r in scored)
        result["beat_or_tie"] = won
        result["beat_or_tie_pct"] = round(won / len(scored) * 100, 1)
        result["gate_met"] = won / len(scored) >= 0.70
        # The denominator is what was scorable, not what magicplan reported. Stating the gap
        # stops a 70% over 6 dimensions reading like a 70% over 14.
        result["gate_denominator_note"] = (
            f"{len(scored)} of {len(rows)} magicplan dimensions were scorable; the percentage "
            f"above is over the {len(scored)}, not the {len(rows)}")

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

    # relative_to raises when OUT is redirected outside the repo, which the tests do. A
    # cosmetic path in a log line must never be able to fail the run that produced the result.
    print(f"\nwrote {OUT.relative_to(ROOT) if OUT.is_relative_to(ROOT) else OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
