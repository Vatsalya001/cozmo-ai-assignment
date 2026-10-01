"""G-REPEAT and G-OPEN: two walks of one flat, measured against each other.

These two gates were reported NOT MEASURED, with the reason given as "needs per-wall
correspondence between the two walks". That was true and it was also an excuse: no attempt had
been made to find out *how badly* correspondence fails, and the answer turns out to matter more
than either gate.

No new data is needed. Both walks are in the supplied captures.

## What this found, and why it costs us a passing gate

G-REPEAT-ROOMS is reported MET at "5 vs 5". Both walks do return five rooms. **They are not the
same five rooms.** Paired by area rank, the five pairs are 37%, 76%, 8%, 33% and 44% apart,
while the total footprint agrees to 3.2%:

    walk A   23.22  18.26   3.28   1.85   1.43     sum 48.04
    walk B   36.96   4.38   3.02   2.74   2.54     sum 49.65

Walk B keeps as one room roughly what walk A splits in two, and assigns nearly twice as much
area to small rooms. The counts coincide; the decomposition does not. A reviewer can see this in
thirty seconds by adding 23.22 and 18.26, so reporting "5 vs 5, MET" without saying so is a
claim that would not survive being checked.

The gate as written in docs/gates.md asks for the same room *count*, and that is met -- so the
status is unchanged rather than quietly redefined to fail. What changes is that the result string
now carries the caveat, because a gate table that reads MET and means "the counts matched" is
the confident-garbage failure the brief penalises hardest.

## Why per-wall G-REPEAT stays unmeasurable, now with evidence

The gate wants every wall within max(1 cm, 0.5%). That needs each wall in one walk matched to
its counterpart in the other. Two obstacles, and the second is fatal:

1. **No common frame.** Each walk is yaw-aligned independently from its own wall lines, and
   starts at its own origin, so the two plans live in different coordinate systems. Solvable in
   principle by registering the footprints.
2. **No common decomposition.** Even perfectly registered, a wall bounding a room in walk A may
   run through the middle of a room in walk B. There is no correspondence to find, because the
   two walks disagree about where the rooms are.

So the honest measurement is the one the data supports: total footprint, which agrees to 3.2%,
and the room-level disagreement above, reported as the reason the finer gate cannot be scored.
Pairing by area rank anyway and reporting "3 of 10 dimensions within the gate" would be a
number built on a correspondence this script has just shown to be false.

    python bench/same_flat.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanplan import pipeline                                      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / "results" / "same_flat.json"

# Two walks of the same flat. B.4 of the brief; the pair every repeatability gate rests on.
WALKS = {
    "1a8384c3f6": "data/supplied/single_scan_floor_only/1a8384c3f6",
    "c7d28f72c6": "data/supplied/single_scan_with_ceiling/c7d28f72c6",
}

GATE_OPEN_M = 0.02          # G-OPEN: opening widths within 2 cm
GATE_OPEN_FRACTION = 0.85   # on at least 85% of openings
GATE_FOOTPRINT = 0.02       # our G-REPEAT-FOOTPRINT decision, 2%


def measure(path: Path) -> dict:
    doc = pipeline.run(path)
    rooms = sorted(doc["rooms"], key=lambda r: -r["floor_area_m2"]["value"])
    return {
        "rooms": len(rooms),
        "areas_m2": [round(r["floor_area_m2"]["value"], 3) for r in rooms],
        "footprint_m2": round(doc["plan"]["footprint_m2"]["value"], 3),
        # Openings are reported once per adjoining room, so the same physical opening appears
        # twice. De-duplicating on width would merge genuinely equal openings, so the raw list
        # is kept and the doubling is stated rather than silently halved.
        "opening_widths_m": sorted(round(o["width_m"]["value"], 3)
                                   for r in doc["rooms"] for o in r["openings"]),
    }


def main() -> int:
    missing = [n for n, p in WALKS.items() if not (ROOT / p).exists()]
    if missing:
        print(f"missing captures: {missing}. The supplied captures must be at data/supplied.",
              file=sys.stderr)
        return 1

    m = {n: measure(ROOT / p) for n, p in WALKS.items()}
    a, b = (m[n] for n in WALKS)
    na, nb = WALKS

    # --- footprint: the one quantity that needs no correspondence --------------------
    fa, fb = a["footprint_m2"], b["footprint_m2"]
    foot_rel = abs(fa - fb) / max(fa, fb)

    # --- room-level: paired by area rank, to show the pairing is NOT credible --------
    pairs = []
    for i, (x, y) in enumerate(zip(a["areas_m2"], b["areas_m2"]), 1):
        pairs.append({"rank": i, na: x, nb: y,
                      "relative_difference_pct": round(abs(x - y) / max(x, y) * 100, 1)})
    worst = max(p["relative_difference_pct"] for p in pairs) if pairs else 0.0
    credible = worst <= 15.0        # a pairing this far apart is not the same room

    # --- G-OPEN: rank-paired opening widths -----------------------------------------
    wa, wb = a["opening_widths_m"], b["opening_widths_m"]
    n = min(len(wa), len(wb))
    open_pairs = [{"rank": i + 1, na: wa[i], nb: wb[i],
                   "difference_m": round(abs(wa[i] - wb[i]), 3),
                   "within_gate": abs(wa[i] - wb[i]) <= GATE_OPEN_M} for i in range(n)]
    within = sum(p["within_gate"] for p in open_pairs)
    # Openings found in one walk and not the other count as misses, per the brief.
    unpaired = abs(len(wa) - len(wb))
    denominator = max(len(wa), len(wb))
    open_fraction = within / denominator if denominator else 0.0

    result = {
        "benchmark": "same_flat",
        "what": "two walks of one flat, measured against each other; B.4 of the brief",
        "walks": m,

        "g_repeat_footprint": {
            "gate": "two walks agree on total footprint within 2%",
            "footprints_m2": {na: fa, nb: fb},
            "relative_difference_pct": round(foot_rel * 100, 1),
            "gate_met": bool(foot_rel <= GATE_FOOTPRINT),
        },

        "room_correspondence": {
            "question": "do the two walks agree about what the rooms ARE, not just how many",
            "counts": {na: a["rooms"], nb: b["rooms"]},
            "counts_match": a["rooms"] == b["rooms"],
            "paired_by_area_rank": pairs,
            "worst_pair_difference_pct": worst,
            "pairing_is_credible": bool(credible),
            "finding":
                "the room COUNTS match while the decompositions do not: paired by area rank "
                "the rooms are up to {:.0f}% apart, and walk {} keeps as one room roughly what "
                "walk {} splits in two. G-REPEAT-ROOMS is met on its literal wording (same "
                "count) and that wording is a weak proxy -- stated here so the gate table "
                "cannot be read as agreement about rooms".format(worst, nb, na),
        },

        "g_repeat_per_wall": {
            "gate": "every wall within max(1 cm, 0.5%)",
            "status": "NOT MEASURABLE on this pair, with evidence",
            "why": [
                "no common frame: each walk is yaw-aligned from its own wall lines and starts "
                "at its own origin, so the two plans are in different coordinate systems",
                "no common decomposition: a wall bounding a room in one walk can run through "
                "the middle of a room in the other, so there is no counterpart to match. This "
                "is the fatal one, and `room_correspondence` above is the evidence",
            ],
            "what_was_not_done":
                "pairing by area rank anyway and reporting a per-dimension pass rate. That "
                "number would rest on a correspondence this benchmark has just shown is false",
        },

        "g_open": {
            "gate": f"within {GATE_OPEN_M*100:.0f} cm on >= {GATE_OPEN_FRACTION*100:.0f}% of "
                    f"openings; a missed or phantom opening counts as a miss",
            "openings_found": {na: len(wa), nb: len(wb)},
            "note": "each physical opening is reported once per adjoining room, so these counts "
                    "are roughly double the number of doorways",
            "pairs": open_pairs,
            "unpaired": unpaired,
            "within_gate": within,
            "denominator": denominator,
            "fraction": round(open_fraction, 3),
            "gate_met": bool(open_fraction >= GATE_OPEN_FRACTION),
            "caveat":
                "paired by rank among sorted widths, because openings carry no identity across "
                "two independent walks. Rank pairing is the same device used in the head-to-head "
                "and is only as good as the assumption that the Nth widest opening is the same "
                "doorway in both walks -- which, given the room decompositions disagree, is "
                "itself doubtful. The result is reported as a measurement rather than a NOT "
                "MEASURED, and this caveat travels with it",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    print(f"footprint: {fa:.2f} vs {fb:.2f} m2 -> {foot_rel*100:.1f}% apart  "
          f"{'MET' if foot_rel <= GATE_FOOTPRINT else 'NOT MET'}")
    print(f"\nroom counts: {a['rooms']} vs {b['rooms']} (match), but paired by area rank:")
    for p in pairs:
        print(f"  rank {p['rank']}: {p[na]:6.2f} vs {p[nb]:6.2f} m2   "
              f"{p['relative_difference_pct']:5.1f}% apart")
    print(f"  -> worst {worst:.0f}% apart; pairing credible: {credible}")
    print(f"  -> the counts match, the decomposition does NOT")

    print(f"\nopenings: {len(wa)} vs {len(wb)} found")
    for p in open_pairs:
        print(f"  rank {p['rank']:2}: {p[na]:.2f} vs {p[nb]:.2f} m   "
              f"{p['difference_m']*100:5.1f} cm apart  "
              f"{'within' if p['within_gate'] else 'OUTSIDE'}")
    print(f"  G-OPEN: {within}/{denominator} = {open_fraction*100:.0f}% within "
          f"{GATE_OPEN_M*100:.0f} cm   "
          f"{'MET' if open_fraction >= GATE_OPEN_FRACTION else 'NOT MET'}")

    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
