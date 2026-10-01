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
    # The measured seconds go in `detail`, never in `result`. A wall-clock number inside the
    # result string makes this file differ on every run, and a clean-clone check then cannot
    # tell a real regression from a slightly busier machine.
    add("A-RUNTIME", "lidar", f"<= {RUNTIME_BUDGET_S:.0f} s",
        "within budget" if worst <= RUNTIME_BUDGET_S else "over budget",
        "MET" if worst <= RUNTIME_BUDGET_S else "NOT MET",
        "measured seconds vary with the machine and are reported in timing.json, not here")
    (OUT / "timing.json").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "timing.json").write_text(json.dumps(
        {"budget_s": RUNTIME_BUDGET_S, "worst_s": round(worst, 1),
         "per_capture_s": {k: round(v, 1) for k, v in times.items()},
         "note": "wall-clock, machine-dependent; excluded from gates.json so that file "
                 "reproduces exactly"}, indent=2) + "\n")

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
    _cw = ROOT / "bench" / "results" / "ceiling_walks.json"
    _ceil = json.loads(_cw.read_text()) if _cw.is_file() else None
    if _ceil and _ceil.get("spread_within_venue_mm"):
        # Measured where the gate actually means something: repeated walks of ONE venue.
        # The old proxy compared three unrelated captures, which cannot be a spread.
        sp = _ceil["spread_within_venue_mm"]
        add("G-CEIL-SPREAD", "lidar", "<= 1 cm across walks of one venue",
            ", ".join(f"{v} {s:.1f} mm" for v, s in sp.items()),
            "MET" if _ceil["spread_gate"]["gate_met"] else "NOT MET",
            f"venues within the 10 mm target: {_ceil['spread_gate']['venues_within']}. "
            f"Repeated walks of the same venue, which is what 'spread' requires; the earlier "
            f"row compared three unrelated captures and could not answer the question")
    elif len(ceilings) >= 2:
        spread = max(ceilings.values()) - min(ceilings.values())
        add("G-CEIL-SPREAD", "lidar", "<= 1 cm across captures",
            f"{spread*100:.1f} cm", "MET" if spread <= 0.01 else "NOT MET",
            ", ".join(f"{k} {v:.3f} m" for k, v in ceilings.items()))
    else:
        add("G-CEIL-SPREAD", "lidar", "<= 1 cm across captures", "NOT MEASURED",
            "NOT MEASURED", f"only {len(ceilings)} capture(s) saw a ceiling")
    # G-CEIL against FARO laser truth. Reported NOT MEASURED through two earlier attempts;
    # bench/ceiling_walks.py measures it on full ARKitScenes walks. If that file is absent the
    # row falls back to NOT MEASURED rather than silently vanishing.
    cw = ROOT / "bench" / "results" / "ceiling_walks.json"
    ceil_walks = json.loads(cw.read_text()) if cw.is_file() else None
    if ceil_walks and ceil_walks.get("walks_scored"):
        add("G-CEIL", "lidar", "<= 1.5 cm per room vs truth",
            f"{ceil_walks['within_gate']}/{ceil_walks['total']} walks within 15 mm "
            f"(mean {ceil_walks['mean_error_mm']:+.1f} mm)",
            "MET" if ceil_walks["gate_met"] else "NOT MET",
            f"FARO-derived laser depth on the same frames and poses, both streams through our "
            f"own floor/ceiling fit; bias correction {ceil_walks['bias_correction']}, so no "
            f"walk is corrected with its own truth. {ceil_walks['walks_rejected']} walk(s) "
            f"rejected for producing no floor+ceiling pair")
    else:
        add("G-CEIL", "lidar", "<= 1.5 cm per room vs truth", "NOT MEASURED", "NOT MEASURED",
            "run scripts/fetch_arkitscenes_walks.py then bench/ceiling_walks.py")

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
        # The count is what the gate asks for, and it is met. It is also a weak proxy, and
        # bench/same_flat.py showed how weak: the five rooms are up to 76% apart by area, so
        # the two walks agree on how many rooms there are and not on what they are. The caveat
        # rides in the result string, because a table reading MET and meaning "counts matched"
        # is exactly the confident-garbage failure the brief penalises hardest.
        sf = ROOT / "bench" / "results" / "same_flat.json"
        caveat = ""
        if sf.is_file():
            rc = json.loads(sf.read_text())["room_correspondence"]
            if not rc["pairing_is_credible"]:
                caveat = (f" (counts only -- decompositions disagree by up to "
                          f"{rc['worst_pair_difference_pct']:.0f}%, see same_flat.json)")
        add("G-REPEAT-ROOMS", "lidar", "same room count from both walks",
            f"{ra} vs {rb}{caveat}", "MET" if ra == rb else "NOT MET",
            "the gate asks for the count and the count matches; the rooms themselves do not "
            "correspond, which bench/same_flat.py measures")

    sf = ROOT / "bench" / "results" / "same_flat.json"
    same_flat = json.loads(sf.read_text()) if sf.is_file() else None

    if same_flat:
        g = same_flat["g_repeat_per_wall"]
        add("G-REPEAT", "lidar", "every wall within max(1 cm, 0.5%)", "NOT MEASURABLE",
            "NOT MEASURED", "; ".join(g["why"]))
    else:
        add("G-REPEAT", "lidar", "every wall within max(1 cm, 0.5%)", "NOT MEASURED",
            "NOT MEASURED", "needs per-wall correspondence between the two walks")

    # --- G-OPEN: measured walk against walk, no tape needed -------------------------
    if same_flat:
        o = same_flat["g_open"]
        add("G-OPEN", "lidar", "<= 2 cm on >= 85% of openings",
            f"{o['within_gate']}/{o['denominator']} within 2 cm "
            f"({o['fraction']*100:.0f}%)",
            "MET" if o["gate_met"] else "NOT MET",
            f"two walks of one flat, {o['openings_found']}; widths rank-paired. "
            f"{o['caveat'][:120]}")
    else:
        add("G-OPEN", "lidar", "<= 2 cm on >= 85% of openings", "NOT MEASURED", "NOT MEASURED",
            "no tape truth for the supplied captures")
    # The synthetic figures deliberately are NOT repeated here. They were, and they went stale
    # the moment the depth-bias correction changed them -- a hardcoded cross-reference to a
    # number that lives in another file is a number that will be wrong eventually.
    add("A-WALL-LIDAR", "lidar", "<= max(2 cm, 1%)", "NOT MEASURED", "NOT MEASURED",
        "no tape truth for the supplied captures; the synthetic room of exactly known size is "
        "measured by tests/test_accuracy.py and tabulated in docs/technical_report.md section 6")
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

    # The same question against an opponent that CAN be handed our exact input. Reported as a
    # separate gate, never folded into G-H2H: the brief asks Part 3 for a consumer scanning
    # app, and another engineer's submission is not one.
    he = ROOT / "bench" / "results" / "head_to_head_engineer.json"
    if he.is_file():
        h = json.loads(he.read_text())
        if h.get("dimensions_scored"):
            add("G-H2H-ENGINEER", "lidar",
                "beat or tie an independent implementation on >= 70%",
                f"{h['beat_or_tie']}/{h['dimensions_scored']} = {h['beat_or_tie_pct']}%",
                "MET" if h["gate_met"] else "NOT MET",
                f"{h['opponent']['name']} @ {h['opponent']['commit']} on identical synthetic "
                f"captures with exact truth; supplementary to Part 3, not a substitute")
        else:
            add("G-H2H-ENGINEER", "lidar",
                "beat or tie an independent implementation on >= 70%",
                "NOT MEASURED", "NOT MEASURED", "; ".join(h.get("notes", [])) or "no scored rows")
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
    # The drift ablation per capture, published rather than left inside the G-DRIFT detail
    # string. docs/technical_report.md §3 tabulates these, and a table transcribed by hand from
    # a sentence is a table that goes stale -- which is exactly what happened to it once.
    drift_table = {}
    for k, v in runs.items():
        d = v["on"]["plan"]["drift"]
        drift_table[k] = {
            "loop_closures": d["loop_closures"], "submaps": d["submaps"],
            "max_shift_mm": round(d["max_shift_m"] * 1000, 1),
            "mean_shift_mm": round(d["mean_shift_m"] * 1000, 1),
            "footprint_off_m2": v["off"]["plan"]["footprint_m2"]["value"],
            "footprint_on_m2": v["on"]["plan"]["footprint_m2"]["value"],
        }

    (OUT / "gates.json").write_text(json.dumps(
        {"rows": rows,
         "footprints": {k: v["on"]["plan"]["footprint_m2"]["value"] for k, v in runs.items()},
         "rooms": {k: len(v["on"]["rooms"]) for k, v in runs.items()},
         "drift_ablation": drift_table}, indent=2) + "\n")

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
