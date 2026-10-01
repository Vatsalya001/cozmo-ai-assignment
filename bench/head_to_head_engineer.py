"""Head-to-head against another engineer's independent implementation, on exact truth.

## Why this exists alongside the magicplan comparison

Part 3 of the brief asks for a comparison against a **consumer scanning app**, and that is
`bench/head_to_head.py` -- magicplan 2026.38.0, captured and committed. It cannot be scored:
scoring needs tape truth for the rooms magicplan measured, and that does not exist. It stays
PENDING and this file does not replace it.

What this file does is something the magicplan comparison cannot do at all. Both pipelines read
the public Stray Scanner format, so both can be handed **the same synthetic capture of a room
whose size is known by construction** -- 4.00 x 3.00 m, 2.50 m ceiling, because an equation put
them there. No tape, no fieldwork, and the truth is exact rather than +-5 mm.

Opponent: **cozmo-scan** by Ashu Pal, an independent submission to the same brief. Not a
consumer app, so this is supplementary evidence, not Part 3 compliance.

## The experiment is designed so it can lose

A synthetic capture encodes an assumption about the sensor, and that assumption decides the
result. So the comparison runs on **two** captures that differ in exactly one way:

  biased   depth written 18 mm SHORT, which is what the device was MEASURED to do
           (bench/depth_bias.py, 4.79 M pixels against FARO laser truth)
  ideal    depth written true, modelling a sensor with no bias

These two pipelines take opposite positions on that question. scanplan measured the bias and
corrects it at ingest. cozmo-scan carries it as an uncertainty of 13 mm and applies no
correction (`depth_offset_m` defaults to 0.0 in its fusion stage). Both are defensible designs,
and each is right on exactly one of these two captures.

Running only the `biased` capture would be choosing the input that suits us. Running both, and
reporting both, is the honest version -- and the split result is more informative than either
half, because it shows the comparison turns on a question of fact about the sensor rather than
on craft. That question was settled by measurement against a laser, not by argument.

## What this cannot show

Synthetic geometry flatters both pipelines: no furniture, no occlusion, no reflective surfaces,
perfectly flat walls, noiseless depth. These numbers bound what each implementation does to
clean input. They say nothing about robustness on real rooms, and a pipeline tuned on real
captures may well be penalised here for choices that pay off on real ones.

    python bench/head_to_head_engineer.py
    python bench/head_to_head_engineer.py --refresh-opponent ~/Desktop/cozmo-scan

Without --refresh-opponent the opponent's numbers are read from data/opponents/cozmo-scan.json,
committed so this runs, and can be audited, without their repository present.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanplan import pipeline                                      # noqa: E402
from scanplan.synthetic import write_stray_capture                 # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "results" / "head_to_head_engineer.json"
OPPONENT_FILE = ROOT / "data" / "opponents" / "cozmo-scan.json"

# One capture per position on the sensor-bias question. See the module docstring.
CAPTURES = {
    "biased": {"device_bias_m": 0.018,
               "models": "the device as MEASURED: reads 18 mm short of laser truth"},
    "ideal": {"device_bias_m": 0.0,
              "models": "an ideal sensor with no bias"},
}

# Lower is better for all of these; each is an absolute error in metres against exact truth.
DIMENSIONS = ("floor area", "ceiling height", "long dimension", "short dimension", "perimeter")


def dimensions_from(doc: dict) -> dict[str, float]:
    """The five comparable quantities, from either pipeline's result document.

    Both write the same field names for area, perimeter and ceiling height. The two room
    dimensions are taken as the extent of the room polygon's bounding box, which is well
    defined regardless of how either implementation split the outline into wall segments --
    pairing named walls across two independent implementations is not possible, and taking
    whichever wall is closest to truth would flatter whoever reports more of them.
    """
    if not doc.get("rooms"):
        return {}
    room = max(doc["rooms"], key=lambda r: r["floor_area_m2"]["value"])
    poly = np.asarray(room["polygon"], dtype=float)
    span = sorted(poly.max(axis=0) - poly.min(axis=0), reverse=True)
    return {
        "floor area": float(room["floor_area_m2"]["value"]),
        "ceiling height": float(room["ceiling_height_m"]["value"]),
        "long dimension": float(span[0]),
        "short dimension": float(span[1]),
        "perimeter": float(room["perimeter_m"]["value"]),
        "_rooms": len(doc["rooms"]),
    }


def truth_of(t: dict) -> dict[str, float]:
    return {
        "floor area": t["area_m2"],
        "ceiling height": t["ceiling_m"],
        "long dimension": max(t["width_m"], t["depth_m"]),
        "short dimension": min(t["width_m"], t["depth_m"]),
        "perimeter": t["perimeter_m"],
    }


def run_opponent(repo: Path, capture: Path, out: Path) -> dict:
    """Run cozmo-scan through its own CLI in its own virtualenv.

    Via subprocess on purpose: importing another project into this one would mix two sets of
    module-level constants, and the thing being compared is each project as it ships.
    """
    exe = repo / ".venv" / "bin" / "cozmo"
    if not exe.is_file():
        raise SystemExit(f"{exe}: not found. The opponent repo needs its own venv "
                         f"(python3 -m venv .venv && .venv/bin/pip install -e '.[dev]')")
    done = subprocess.run([str(exe), "run", str(capture), "--out", str(out)],
                          capture_output=True, text=True)
    result = out / "result.json"
    if done.returncode != 0 or not result.is_file():
        return {"failed": (done.stderr or done.stdout or "no output").strip().splitlines()[-1]}
    return json.loads(result.read_text())


def opponent_version(repo: Path) -> dict:
    def git(*a):
        try:
            return subprocess.run(["git", "-C", str(repo), *a],
                                  capture_output=True, text=True).stdout.strip()
        except Exception:                                      # noqa: BLE001
            return "unknown"
    return {"name": "cozmo-scan", "author": "Ashu Pal",
            "repo": "https://github.com/ashupal22/cozmo-scan",
            "commit": git("rev-parse", "--short", "HEAD"),
            "note": "an independent submission to the same brief; NOT a consumer scanning app, "
                    "so this supplements Part 3 rather than satisfying it"}


def refresh(repo: Path) -> dict:
    """Measure the opponent on both captures and commit the numbers."""
    record = {"opponent": opponent_version(repo), "captures": {}}
    work = Path(tempfile.mkdtemp(prefix="h2h_opponent_"))
    for name, spec in CAPTURES.items():
        cap = work / name
        write_stray_capture(cap, device_bias_m=spec["device_bias_m"])
        doc = run_opponent(repo, cap, work / f"out_{name}")
        record["captures"][name] = (doc if "failed" in doc else dimensions_from(doc))
        print(f"  opponent on {name}: "
              f"{record['captures'][name].get('failed') or record['captures'][name]}")
    OPPONENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OPPONENT_FILE.write_text(json.dumps(record, indent=2) + "\n")
    print(f"wrote {OPPONENT_FILE.relative_to(ROOT)}")
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh-opponent", metavar="REPO",
                    help="run the opponent's CLI from its checkout and re-record its numbers")
    args = ap.parse_args()

    if args.refresh_opponent:
        record = refresh(Path(args.refresh_opponent).expanduser())
    elif OPPONENT_FILE.is_file():
        record = json.loads(OPPONENT_FILE.read_text())
    else:
        print(f"{OPPONENT_FILE.relative_to(ROOT)} is missing and --refresh-opponent was not "
              f"given, so there is nothing to compare against", file=sys.stderr)
        return 1

    work = Path(tempfile.mkdtemp(prefix="h2h_ours_"))
    rows, notes = [], []
    for name, spec in CAPTURES.items():
        cap = work / name
        t = write_stray_capture(cap, device_bias_m=spec["device_bias_m"])
        truth = truth_of(t)

        try:
            ours = dimensions_from(pipeline.run(cap))
        except Exception as e:                                 # noqa: BLE001 -- a failure is data
            ours = {}
            notes.append(f"scanplan failed on the {name} capture: {type(e).__name__}: {e}")

        theirs = record["captures"].get(name, {})
        if "failed" in theirs:
            notes.append(f"cozmo-scan failed on the {name} capture: {theirs['failed']}")

        for dim in DIMENSIONS:
            row = {"capture": name, "models": spec["models"], "dimension": dim,
                   "truth": round(truth[dim], 4)}
            o, p = ours.get(dim), theirs.get(dim)
            row["scanplan"] = None if o is None else round(o, 4)
            row["cozmo_scan"] = None if p is None else round(p, 4)
            if o is not None:
                row["scanplan_error_m"] = round(abs(o - truth[dim]), 4)
            if p is not None:
                row["cozmo_scan_error_m"] = round(abs(p - truth[dim]), 4)
            if o is not None and p is not None:
                # Beat or tie, with a 1 mm tolerance so a rounding difference is not a loss.
                row["we_beat_or_tie"] = row["scanplan_error_m"] <= row["cozmo_scan_error_m"] + 0.001
            else:
                row["not_scored_because"] = (
                    "one or both pipelines produced no value for this capture")
            rows.append(row)

    scored = [r for r in rows if "we_beat_or_tie" in r]
    won = sum(r["we_beat_or_tie"] for r in scored)
    result = {
        "gate": "G-H2H-ENGINEER: beat or tie an independent implementation on >= 70% of "
                "shared dimensions, against exact synthetic truth",
        "opponent": record["opponent"],
        "relationship_to_part_3":
            "Part 3 asks for a consumer scanning app and is bench/head_to_head.py (magicplan, "
            "PENDING for want of tape truth). This is supplementary: an independent engineer's "
            "implementation, which unlike an app can be handed the identical input, so the "
            "comparison carries exact truth instead of a tape reading",
        "method":
            "both pipelines read the public Stray Scanner format, so both measure the SAME "
            "synthetic capture of a room that is 4.00 x 3.00 m with a 2.50 m ceiling by "
            "construction. Room dimensions are the polygon bounding box, not named walls: two "
            "independent implementations share no wall identities, and matching each of theirs "
            "to whichever of ours is closest would flatter whoever reports more walls",
        "why_two_captures":
            "a synthetic capture encodes an assumption about the sensor, and these two "
            "pipelines take opposite positions on it. scanplan measured an 18 mm bias against "
            "FARO laser truth and corrects it; cozmo-scan carries 13 mm as an uncertainty and "
            "corrects nothing. Running only the capture that suits us would be choosing the "
            "input. Both are run and both are reported",
        "caveat":
            "synthetic geometry flatters both: no furniture, no occlusion, no reflective "
            "surfaces, noiseless depth. This bounds what each implementation does to clean "
            "input and says nothing about robustness on real rooms",
        "rows": rows,
        "dimensions_total": len(rows),
        "dimensions_scored": len(scored),
        "notes": notes,
    }
    if scored:
        result.update({
            "beat_or_tie": won,
            "beat_or_tie_pct": round(won / len(scored) * 100, 1),
            "gate_met": won / len(scored) >= 0.70,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    print(f"\n{'capture':8} {'dimension':16} {'truth':>8} {'scanplan':>18} {'cozmo-scan':>18}  winner")
    for r in rows:
        o = f"{r['scanplan']:.3f} ({r.get('scanplan_error_m', float('nan'))*1000:+.0f}mm)" \
            if r["scanplan"] is not None else "-"
        p = f"{r['cozmo_scan']:.3f} ({r.get('cozmo_scan_error_m', float('nan'))*1000:+.0f}mm)" \
            if r["cozmo_scan"] is not None else "-"
        w = ("scanplan" if r["we_beat_or_tie"] else "cozmo-scan") if "we_beat_or_tie" in r else "-"
        print(f"{r['capture']:8} {r['dimension']:16} {r['truth']:8.3f} {o:>18} {p:>18}  {w}")
    for n in notes:
        print(f"  note: {n}")
    if scored:
        print(f"\n  beat or tie on {won}/{len(scored)} = {result['beat_or_tie_pct']}%   "
              f"gate {'MET' if result['gate_met'] else 'NOT MET'} (target 70%)")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
