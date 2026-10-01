"""Build the reviewer's bundle: every tier's output for every capture, committed.

A reviewer who will not install anything should still be able to see what this pipeline
produces. The repo regenerates everything in one command, which is better engineering and worse
for a reader with ten minutes — so the outputs are built here and committed.

Committed rather than put behind a file-sharing link, on purpose: a link rots, is not versioned,
and cannot be diffed. These are small (result.json, plan.svg, summary.md and a one-page
report.pdf per capture; report.png is skipped as it is the largest file and adds nothing a
reviewer cannot see in the PDF).

## What gets built, and what legitimately fails

    LiDAR   all three supplied captures
    video   the same three; c7d28f72c6 FAILS with a stated "no floor found" and the failure is
            recorded in the index rather than omitted -- the video tier's inferred depth is too
            inconsistent on that capture to form a floor level, which is a result
    photo   the derived photo set (scripts/build_photoset.py)

A tier that fails on a capture is written to the index with its error. An absent row would read
as "not attempted", which is the opposite of what happened.

    python scripts/build_submission_bundle.py
    python scripts/build_submission_bundle.py --lidar-only    # no model extra needed
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "submission" / "outputs"

SUPPLIED = ROOT / "data" / "supplied"
CAPTURES = {
    "c00a170fe1": SUPPLIED / "single_room" / "c00a170fe1",
    "1a8384c3f6": SUPPLIED / "single_scan_floor_only" / "1a8384c3f6",
    "c7d28f72c6": SUPPLIED / "single_scan_with_ceiling" / "c7d28f72c6",
}

# report.png is deliberately not copied: it is the largest artifact and duplicates the PDF.
KEEP = ("result.json", "plan.svg", "summary.md", "report.pdf")


def run_one(tier: str, name: str, path: Path, dest: Path) -> dict:
    from scanplan import pipeline
    from scanplan.export import render
    from scanplan.validate import validate

    started = time.perf_counter()
    try:
        doc = pipeline.run(path, tier=tier)
    except Exception as e:                                  # noqa: BLE001 -- a failure is data
        return {"tier": tier, "capture": name, "status": "failed",
                "error": f"{type(e).__name__}: {e}".replace(str(ROOT), "."),
                "seconds": round(time.perf_counter() - started, 1)}

    problems = validate(doc)
    if problems:
        return {"tier": tier, "capture": name, "status": "schema_invalid",
                "error": "; ".join(problems[:3]),
                "seconds": round(time.perf_counter() - started, 1)}

    work = dest.parent / f".{dest.name}.tmp"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "result.json").write_text(json.dumps(doc, indent=2) + "\n")
    render.write_all(doc, work)

    dest.mkdir(parents=True, exist_ok=True)
    for f in KEEP:
        src = work / f
        if src.is_file():
            shutil.copy2(src, dest / f)
    shutil.rmtree(work)

    fp = doc["plan"]["footprint_m2"]
    return {"tier": tier, "capture": name, "status": "ok",
            "rooms": len(doc["rooms"]),
            "footprint_m2": round(fp["value"], 2),
            "footprint_ci": [round(fp["ci_low"], 2), round(fp["ci_high"], 2)],
            "interval_widening": doc["quality"]["interval_widening_factor"],
            "warnings": len(doc["quality"]["warnings"]),
            "files": sorted(f.name for f in dest.iterdir() if f.is_file()),
            "seconds": round(time.perf_counter() - started, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lidar-only", action="store_true",
                    help="skip the tiers that need the model extra")
    args = ap.parse_args()

    missing = [n for n, p in CAPTURES.items() if not p.exists()]
    if missing:
        print(f"captures missing: {missing}. data/supplied must be present (a symlink is fine).",
              file=sys.stderr)
        return 1

    jobs = [("lidar", n, p) for n, p in CAPTURES.items()]
    if not args.lidar_only:
        jobs += [("video", n, p) for n, p in CAPTURES.items()]
        photoset = ROOT / "data" / "derived" / "photoset"
        if not any(photoset.glob("*/*.jpg")):
            from scripts.build_photoset import CAPTURE, build
            print(f"building the photo set from {CAPTURE.name}")
            build(CAPTURE, photoset)
        jobs += [("photo", "photoset", photoset)]

    rows = []
    for tier, name, path in jobs:
        dest = OUT / tier / name
        print(f"{tier:6} {name} ...", flush=True)
        row = run_one(tier, name, path, dest)
        rows.append(row)
        if row["status"] == "ok":
            print(f"       {row['rooms']} rooms, {row['footprint_m2']} m2, "
                  f"{row['seconds']} s -> submission/outputs/{tier}/{name}/")
        else:
            print(f"       {row['status'].upper()}: {row['error']}")

    index = {
        "what": "every tier's output for every capture, so a reviewer who will not install "
                "anything can still see what the pipeline produces",
        "why_committed": "a file-sharing link rots, is not versioned and cannot be diffed",
        "regenerate": "python scripts/build_submission_bundle.py",
        "note": "report.png is not included; it duplicates report.pdf and is the largest file. "
                "A tier that FAILED on a capture is listed with its error rather than omitted, "
                "because an absent row reads as 'not attempted'",
        "rows": rows,
        "ok": sum(1 for r in rows if r["status"] == "ok"),
        "failed": sum(1 for r in rows if r["status"] != "ok"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(index, indent=2) + "\n")

    md = ["# Submission outputs", "",
          "Every tier's output for every capture. Generated by",
          "`python scripts/build_submission_bundle.py`; committed so a reviewer who will not",
          "install anything can still see what the pipeline produces.", "",
          "| Tier | Capture | Rooms | Footprint (m²) | 90% interval | Widening | Warnings | Files |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["status"] == "ok":
            md.append(f"| {r['tier']} | {r['capture']} | {r['rooms']} | {r['footprint_m2']} | "
                      f"{r['footprint_ci'][0]}–{r['footprint_ci'][1]} | ×{r['interval_widening']:.0f} | "
                      f"{r['warnings']} | {', '.join(r['files'])} |")
        else:
            md.append(f"| {r['tier']} | {r['capture']} | — | **{r['status']}** | — | — | — | "
                      f"`{r['error'][:90]}` |")
    md += ["", f"**{index['ok']} produced, {index['failed']} failed.** A failing tier is listed "
               "with its error rather than omitted: an absent row reads as *not attempted*, "
               "which is not what happened.", ""]
    (OUT / "README.md").write_text("\n".join(md) + "\n")

    print(f"\n{index['ok']} produced, {index['failed']} failed")
    print(f"wrote {(OUT / 'README.md').relative_to(ROOT)} and index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
