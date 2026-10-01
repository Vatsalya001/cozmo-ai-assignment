"""Run every gate that current data can answer, and say plainly which it cannot.

The fix loop has to name "the single worst-performing gate in your own benchmark", so the
gates must be measured before anything can be declared. A gate with no data behind it is
reported as NOT MEASURED rather than silently omitted -- an absent row reads as a pass to a
hurried reader, which is the opposite of what it means.

    python bench/gates.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanplan import pipeline                                     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SUPPLIED = ROOT / "data" / "supplied"
OUT = ROOT / "bench" / "results"

CAPTURES = {
    "c00a170fe1": SUPPLIED / "single_room" / "c00a170fe1",
    "1a8384c3f6": SUPPLIED / "single_scan_floor_only" / "1a8384c3f6",
    "c7d28f72c6": SUPPLIED / "single_scan_with_ceiling" / "c7d28f72c6",
}

# 1a8384c3f6 and c7d28f72c6 are two walks of the same flat, which is what G-REPEAT needs.
REPEAT_PAIR = ("1a8384c3f6", "c7d28f72c6")

RUNTIME_BUDGET_S = 60.0     # A-RUNTIME for the LiDAR tier


def measure_all() -> dict:
    runs = {}
    for name, path in CAPTURES.items():
        if not path.exists():
            print(f"  {name}: MISSING at {path}", file=sys.stderr)
            continue
        t0 = time.perf_counter()
        doc = pipeline.run(path)
        wall = time.perf_counter() - t0
        doc_off = pipeline.run(path, drift=False)
        runs[name] = {"on": doc, "off": doc_off, "wall_s": wall}
        print(f"  {name}: {len(doc['rooms'])} rooms, "
              f"{doc['plan']['footprint_m2']['value']:.2f} m2, {wall:.1f} s")
    return runs


def gate_rows(runs: dict) -> list[dict]:
    rows = []

    def add(gate, tier, target, result, status, detail=""):
        rows.append({"gate": gate, "tier": tier, "target": target,
                     "result": result, "status": status, "detail": detail})

    # --- A-RUNTIME ------------------------------------------------------------------
    times = {k: v["wall_s"] for k, v in runs.items()}
    worst = max(times.values()) if times else float("nan")
    add("A-RUNTIME", "lidar", f"<= {RUNTIME_BUDGET_S:.0f} s",
        f"worst {worst:.1f} s", "MET" if worst <= RUNTIME_BUDGET_S else "NOT MET",
        ", ".join(f"{k} {v:.1f}s" for k, v in times.items()))

    # --- A-DET: determinism ---------------------------------------------------------
    name = next(iter(runs), None)
    if name:
        a = pipeline.run(CAPTURES[name])
        b = pipeline.run(CAPTURES[name])
        for d in (a, b):
            d["capture"].pop("runtime_s", None)
        same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        add("A-DET", "lidar", "same input, same output",
            "identical" if same else "DIFFERS", "MET" if same else "NOT MET", name)

    # --- A-SCHEMA -------------------------------------------------------------------
    from scanplan import validate
    bad = {k: validate.validate(v["on"]) for k, v in runs.items()}
    n_bad = sum(1 for v in bad.values() if v)
    add("A-SCHEMA", "all", "100% validate, ci_low <= value <= ci_high",
        f"{len(runs) - n_bad}/{len(runs)} valid", "MET" if n_bad == 0 else "NOT MET")

    # --- G-DRIFT --------------------------------------------------------------------
    detail = []
    for k, v in runs.items():
        on = v["on"]["plan"]["footprint_m2"]["value"]
        off = v["off"]["plan"]["footprint_m2"]["value"]
        d = v["on"]["plan"]["drift"]
        detail.append(f"{k}: {off:.2f} -> {on:.2f} m2, {d['loop_closures']} loops")
    add("G-DRIFT", "lidar", "method stated + footprint ablation on/off",
        "ablation run on all captures", "MET", "; ".join(detail))

    # --- G-CEIL / G-CEIL-SPREAD -----------------------------------------------------
    ceilings = {}
    for k, v in runs.items():
        vals = [r["ceiling_height_m"] for r in v["on"]["rooms"]
                if r["ceiling_height_m"].get("observed", True)]
        if vals:
            ceilings[k] = float(np.mean([c["value"] for c in vals]))
    if len(ceilings) >= 2:
        spread = max(ceilings.values()) - min(ceilings.values())
        add("G-CEIL-SPREAD", "lidar", "<= 1 cm across captures",
            f"{spread*100:.1f} cm", "MET" if spread <= 0.01 else "NOT MET",
            ", ".join(f"{k} {v:.3f} m" for k, v in ceilings.items()))
    else:
        add("G-CEIL-SPREAD", "lidar", "<= 1 cm across captures", "NOT MEASURED",
            "NOT MEASURED", f"only {len(ceilings)} capture(s) saw a ceiling")
    add("G-CEIL", "lidar", "<= 1.5 cm per room vs truth", "NOT MEASURED", "NOT MEASURED",
        "no laser or tape truth for the supplied captures; "
        "bench/arkitscenes_laser.py found no admissible scan")

    # --- G-REPEAT -------------------------------------------------------------------
    a_name, b_name = REPEAT_PAIR
    if a_name in runs and b_name in runs:
        fa = runs[a_name]["on"]["plan"]["footprint_m2"]["value"]
        fb = runs[b_name]["on"]["plan"]["footprint_m2"]["value"]
        rel = abs(fa - fb) / max(fa, fb)
        add("G-REPEAT-FOOTPRINT", "lidar", "two walks of one flat agree",
            f"{rel*100:.1f}% apart", "MET" if rel <= 0.02 else "NOT MET",
            f"{a_name} {fa:.2f} m2 vs {b_name} {fb:.2f} m2")
        ra, rb = len(runs[a_name]["on"]["rooms"]), len(runs[b_name]["on"]["rooms"])
        add("G-REPEAT-ROOMS", "lidar", "same room count from both walks",
            f"{ra} vs {rb}", "MET" if ra == rb else "NOT MET")
    add("G-REPEAT", "lidar", "every wall within max(1 cm, 0.5%)", "NOT MEASURED",
        "NOT MEASURED", "needs per-wall correspondence between the two walks")

    # --- gates that need data we do not have ----------------------------------------
    add("G-OPEN", "lidar", "<= 2 cm on >= 85% of openings", "NOT MEASURED", "NOT MEASURED",
        "no tape truth for the supplied captures")
    add("A-WALL-LIDAR", "lidar", "<= max(2 cm, 1%)", "NOT MEASURED", "NOT MEASURED",
        "no tape truth; synthetic room gives -40 mm and -70 mm on 4.00 and 3.00 m")
    # --- video and photo tiers ------------------------------------------------------
    vv = ROOT / "bench" / "results" / "video_vs_lidar.json"
    if vv.is_file():
        v = json.loads(vv.read_text())
        ok = [r for r in v["rows"] if "footprint_error_pct" in r]
        failed = [r for r in v["rows"] if "video_failed" in r]
        if ok:
            worst = max(abs(r["footprint_error_pct"]) for r in ok)
            add("G-WALL-VIDEO", "video", "within +-3% of reference",
                f"footprint {worst:.0f}% worst over {len(ok)} capture(s)", "NOT MET",
                f"video produced a plan on {len(ok)}/{len(v['rows'])} captures; "
                f"{len(failed)} failed outright. Reference is the LiDAR result, not truth")
            add("A-CALIB-VIDEO", "video", "nominal 90% interval contains the reference",
                f"{v['intervals_holding_at_shipped_factor']}/{len(ok)} at the calibrated "
                f"x{v['shipped_widening_factor']}",
                "MET" if v["intervals_holding_at_shipped_factor"] == len(ok) else "NOT MET",
                "widening factor measured from observed error, not inherited")
    else:
        add("G-WALL-VIDEO", "video", "within +-3%", "NOT RUN", "NOT MEASURED",
            "run bench/video_vs_lidar.py")

    pj = ROOT / "bench" / "results" / "photo_tier.json"
    if pj.is_file():
        p_ = json.loads(pj.read_text())
        add("G-WALL-PHOTO", "photo", "within +-8% of reference",
            f"{p_['rooms']} room box(es), footprint {p_['footprint_m2']:.2f} m2", "NOT MEASURED",
            "no reference exists for the derived photo folders; the tier reports boxes, "
            "not measured walls")
        add("G-PHOTO-STITCH", "photo", "one stitched plan, correct adjacency",
            f"{p_['groups']} disconnected group(s)", "NOT MET",
            "fails by construction: stills carry no poses, so nothing in the input says how "
            "the rooms relate. Reported as an error in every photo-tier run")
    else:
        add("G-WALL-PHOTO", "photo", "within +-8%", "NOT RUN", "NOT MEASURED", "")
        add("G-PHOTO-STITCH", "photo", "one stitched plan", "NOT RUN", "NOT MEASURED", "")
    add("G-H2H", "lidar", "beat or tie on >= 70% of shared dimensions",
        "PENDING", "NOT MEASURED", "magicplan captured; tape measurements outstanding")
    add("A-DMG-DETECT", "all", "staged damage found with right class", "NOT BUILT",
        "NOT MEASURED", "damage detection not implemented")

    return rows


def main() -> int:
    print("running the pipeline on every supplied capture (drift on and off)\n")
    runs = measure_all()
    if not runs:
        print("no captures found", file=sys.stderr)
        return 2

    rows = gate_rows(runs)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gates.json").write_text(json.dumps(
        {"rows": rows,
         "footprints": {k: v["on"]["plan"]["footprint_m2"]["value"] for k, v in runs.items()},
         "rooms": {k: len(v["on"]["rooms"]) for k, v in runs.items()}}, indent=2) + "\n")

    md = ["# Gate results", "",
          "Generated by `bench/gates.py`. Gate definitions in [`docs/gates.md`](../../docs/gates.md).",
          "", "**NOT MEASURED** means exactly that: there is no data behind the row. It is",
          "reported rather than omitted, because an absent row reads as a pass.", "",
          "| Gate | Tier | Target | Result | Status |", "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['gate']} | {r['tier']} | {r['target']} | {r['result']} | "
                  f"**{r['status']}** |")
    md += ["", "## Detail", ""]
    md += [f"- **{r['gate']}** — {r['detail']}" for r in rows if r["detail"]]
    (OUT / "gates.md").write_text("\n".join(md) + "\n")

    print("\n" + "\n".join(f"  {r['status']:<12} {r['gate']:<20} {r['result']}" for r in rows))
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\n  {counts}")
    print(f"\nwrote {(OUT / 'gates.json').relative_to(ROOT)} and gates.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
