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

Opponent: **an independent submission to the same brief** by another engineer, identified here
by commit only. Not a consumer app, so this is supplementary evidence, not Part 3 compliance.

## The experiment is designed so it can lose

A synthetic capture encodes an assumption about the sensor, and that assumption decides the
result. So the comparison runs on **two** captures that differ in exactly one way:

  biased   depth written 18 mm SHORT, which is what the device was MEASURED to do
           (bench/depth_bias.py, 4.79 M pixels against FARO laser truth)
  ideal    depth written true, modelling a sensor with no bias

These two pipelines take opposite positions on that question. scanplan measured the bias and
corrects it at ingest. The independent submission carries it as an uncertainty of 13 mm and
applies no
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
    python bench/head_to_head_engineer.py --refresh-opponent ~/path/to/their/checkout

Without --refresh-opponent the opponent's numbers are read from
data/opponents/independent-submission.json,
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
OPPONENT_FILE = ROOT / "data" / "opponents" / "independent-submission.json"

# One capture per position on the sensor-bias question. See the module docstring.
CAPTURES = {
    "biased": {"device_bias_m": 0.018,
               "models": "the device as MEASURED: reads 18 mm short of laser truth"},
    "ideal": {"device_bias_m": 0.0,
              "models": "an ideal sensor with no bias"},
}

# Lower is better for all of these; each is an absolute error in metres against exact truth.
DIMENSIONS = ("floor area", "ceiling height", "long dimension", "short dimension", "perimeter")

# The real captures carry no truth, so nothing here is scored. They are run and reported anyway
# because the synthetic comparison alone would be a convenient place to stop: it is the one
# input where we can prove we are right. Where the two pipelines disagree on real rooms is the
# more useful question, and on one of these the opponent is closer to the room count this
# project's own declaration cites than we are.
REAL = {
    "c00a170fe1": "data/supplied/single_room/c00a170fe1",
    "1a8384c3f6": "data/supplied/single_scan_floor_only/1a8384c3f6",
    "c7d28f72c6": "data/supplied/single_scan_with_ceiling/c7d28f72c6",
}


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


def summarise(doc: dict) -> dict:
    """Room count, footprint and ceilings -- what can be compared without any truth."""
    fp = doc.get("plan", {}).get("footprint_m2") or doc.get("plan", {}).get("footprint_area_m2")
    return {
        "rooms": len(doc.get("rooms", [])),
        "footprint_m2": round(float(fp["value"] if isinstance(fp, dict) else fp), 3),
        "ceilings_m": sorted({round(r["ceiling_height_m"]["value"], 3)
                              for r in doc.get("rooms", [])}),
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
    """Run the independent submission through its own CLI in its own virtualenv.

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
    return {"name": "an independent submission to the same brief",
            "author": "another engineer; identity withheld, credited by role",
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
    record["real_captures"] = {}
    for name, rel in REAL.items():
        cap = ROOT / rel
        if not cap.exists():
            continue
        doc = run_opponent(repo, cap, work / f"out_real_{name}")
        record["real_captures"][name] = doc if "failed" in doc else summarise(doc)
        print(f"  opponent on real {name}: {record['real_captures'][name]}")

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
            notes.append(f"the independent submission failed on the {name} capture: "
                         f"{theirs['failed']}")

        for dim in DIMENSIONS:
            row = {"capture": name, "models": spec["models"], "dimension": dim,
                   "truth": round(truth[dim], 4)}
            o, p = ours.get(dim), theirs.get(dim)
            row["scanplan"] = None if o is None else round(o, 4)
            row["independent_submission"] = None if p is None else round(p, 4)
            if o is not None:
                row["scanplan_error_m"] = round(abs(o - truth[dim]), 4)
            if p is not None:
                row["independent_submission_error_m"] = round(abs(p - truth[dim]), 4)
            if o is not None and p is not None:
                # Beat or tie, with a 1 mm tolerance so a rounding difference is not a loss.
                row["we_beat_or_tie"] = (row["scanplan_error_m"]
                                         <= row["independent_submission_error_m"] + 0.001)
            else:
                row["not_scored_because"] = (
                    "one or both pipelines produced no value for this capture")
            rows.append(row)

    # --- real captures: no truth, so agreement only, never scored ---------------------
    real_rows, opponent_better = [], []
    for name, rel in REAL.items():
        cap = ROOT / rel
        theirs = (record.get("real_captures") or {}).get(name)
        if not cap.exists() or not theirs or "failed" in theirs:
            continue
        try:
            mine = summarise(pipeline.run(cap))
        except Exception as e:                                 # noqa: BLE001
            notes.append(f"scanplan failed on real capture {name}: {type(e).__name__}: {e}")
            continue
        real_rows.append({"capture": name, "scanplan": mine,
                          "independent_submission": theirs,
                          "footprint_difference_pct": round(
                              (theirs["footprint_m2"] / mine["footprint_m2"] - 1) * 100, 1)})
        if theirs["rooms"] > mine["rooms"]:
            opponent_better.append(
                f"{name}: the independent submission reports {theirs['rooms']} rooms, we report "
                f"{mine['rooms']}. We are documented as under-splitting and this is that, "
                f"measured against an independent implementation rather than asserted")
        # Both pipelines now fit ceiling height PER ROOM, so a difference in the number of
        # distinct heights is a difference in room COUNT, not in the ceiling model. Saying
        # otherwise was true when written and became false when the per-room fit shipped -- the
        # kind of stale comparison that outlives the gap it described.
        if len(theirs["ceilings_m"]) > len(mine["ceilings_m"]):
            opponent_better.append(
                f"{name}: the independent submission reports {len(theirs['ceilings_m'])} "
                f"distinct ceiling "
                f"heights ({theirs['ceilings_m']}) against our {len(mine['ceilings_m'])} "
                f"({mine['ceilings_m']}). Both fit per room now, so this follows from their "
                f"splitting into more rooms rather than from a better ceiling model -- it is "
                f"the room-count gap above, counted a second way, not an independent one")

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
            "FARO laser truth and corrects it; the independent submission carries 13 mm as an "
            "uncertainty and "
            "corrects nothing. Running only the capture that suits us would be choosing the "
            "input. Both are run and both are reported",
        "caveat":
            "synthetic geometry flatters both: no furniture, no occlusion, no reflective "
            "surfaces, noiseless depth. This bounds what each implementation does to clean "
            "input and says nothing about robustness on real rooms",
        "rows": rows,
        "dimensions_total": len(rows),
        "dimensions_scored": len(scored),
        "real_captures_note":
            "the three supplied captures carry NO ground truth, so none of this is scored and "
            "neither pipeline is right by default. It is reported because stopping at the "
            "synthetic comparison would mean reporting only the input where we can prove we "
            "are correct",
        "real_captures": real_rows,
        "where_the_opponent_does_better": opponent_better,
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

    print(f"\n{'capture':8} {'dimension':16} {'truth':>8} {'scanplan':>18} "
          f"{'independent':>18}  winner")
    for r in rows:
        o = f"{r['scanplan']:.3f} ({r.get('scanplan_error_m', float('nan'))*1000:+.0f}mm)" \
            if r["scanplan"] is not None else "-"
        p = (f"{r['independent_submission']:.3f} "
             f"({r.get('independent_submission_error_m', float('nan'))*1000:+.0f}mm)") \
            if r["independent_submission"] is not None else "-"
        w = ("scanplan" if r["we_beat_or_tie"] else "independent") if "we_beat_or_tie" in r else "-"
        print(f"{r['capture']:8} {r['dimension']:16} {r['truth']:8.3f} {o:>18} {p:>18}  {w}")
    for n in notes:
        print(f"  note: {n}")
    if real_rows:
        print(f"\nreal captures (NO truth -- agreement only, nothing scored):")
        print(f"{'capture':12} {'scanplan':>24} {'independent':>24}")
        for r in real_rows:
            m, o = r["scanplan"], r["independent_submission"]
            mine = "{} rooms {:.2f} m2".format(m["rooms"], m["footprint_m2"])
            them = "{} rooms {:.2f} m2".format(o["rooms"], o["footprint_m2"])
            print(f"{r['capture']:12} {mine:>24} {them:>24}")
        for w in opponent_better:
            print(f"  OPPONENT BETTER: {w}")
    if scored:
        print(f"\n  beat or tie on {won}/{len(scored)} = {result['beat_or_tie_pct']}%   "
              f"gate {'MET' if result['gate_met'] else 'NOT MET'} (target 70%)")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
