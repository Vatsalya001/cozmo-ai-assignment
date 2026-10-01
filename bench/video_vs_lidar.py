"""What the video tier costs, and what interval makes it honest.

The same capture is measured twice: once with the depth sensor, once with only RGB and the
pose track. The difference is what inferring depth instead of measuring it costs, which is the
number the video tier exists to report.

It also calibrates the interval. The brief scores calibration at every tier and says confident
garbage on thin input caps the total score, so the widening factor must come from measured
error rather than be inherited from somewhere. A factor that leaves the reference outside the
interval is worse than no interval at all, because it claims a precision that was never there.

The LiDAR result is the reference here, not truth -- there is no tape or laser truth for these
captures. So this measures *agreement between tiers*, and the report says so.

    python bench/video_vs_lidar.py
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
OUT = ROOT / "bench" / "results" / "video_vs_lidar.json"

CAPTURES = {
    "c00a170fe1": SUPPLIED / "single_room" / "c00a170fe1",
    "1a8384c3f6": SUPPLIED / "single_scan_floor_only" / "1a8384c3f6",
    "c7d28f72c6": SUPPLIED / "single_scan_with_ceiling" / "c7d28f72c6",
}

Z90 = 1.645


def main() -> int:
    rows = []
    for name, path in CAPTURES.items():
        if not path.exists():
            continue
        print(f"{name}: lidar ...", flush=True)
        lid = pipeline.run(path)
        print(f"{name}: video ...", flush=True)
        t0 = time.perf_counter()
        try:
            vid = pipeline.run(path, tier="video")
        except Exception as e:                    # noqa: BLE001 -- a failed tier is a result
            wall = time.perf_counter() - t0
            # The message carries the capture's absolute path, which differs on every machine
            # and would make this file disagree with itself in the clean-clone check over
            # something that is not the result. Replaced with the capture name it already has.
            why = f"{type(e).__name__}: {e}".replace(str(path), name).replace(str(ROOT), ".")
            rows.append({"capture": name, "video_failed": why,
                         "lidar_footprint_m2": lid["plan"]["footprint_m2"]["value"],
                         "lidar_rooms": len(lid["rooms"]),
                         "video_runtime_s": round(wall, 1)})
            print(f"  video FAILED after {wall:.0f}s: {e}")
            continue
        wall = time.perf_counter() - t0

        lf = lid["plan"]["footprint_m2"]["value"]
        vf = vid["plan"]["footprint_m2"]["value"]
        row = {
            "capture": name,
            "lidar_footprint_m2": lf, "video_footprint_m2": vf,
            "footprint_error_pct": (vf - lf) / lf * 100,
            "lidar_rooms": len(lid["rooms"]), "video_rooms": len(vid["rooms"]),
            "video_runtime_s": round(wall, 1),
            "video_ci": [vid["plan"]["footprint_m2"]["ci_low"],
                         vid["plan"]["footprint_m2"]["ci_high"]],
            "interval_holds": (vid["plan"]["footprint_m2"]["ci_low"] <= lf
                               <= vid["plan"]["footprint_m2"]["ci_high"]),
        }
        ceil_l = [r["ceiling_height_m"]["value"] for r in lid["rooms"]
                  if r["ceiling_height_m"].get("observed", True)]
        ceil_v = [r["ceiling_height_m"]["value"] for r in vid["rooms"]
                  if r["ceiling_height_m"].get("observed", True)]
        if ceil_l and ceil_v:
            row["lidar_ceiling_m"] = float(np.mean(ceil_l))
            row["video_ceiling_m"] = float(np.mean(ceil_v))
            row["ceiling_error_mm"] = (row["video_ceiling_m"] - row["lidar_ceiling_m"]) * 1000
        rows.append(row)
        print(f"  footprint {vf:.2f} vs {lf:.2f} m2  ({row['footprint_error_pct']:+.1f}%)  "
              f"rooms {row['video_rooms']} vs {row['lidar_rooms']}  {wall:.0f}s  "
              f"interval {'holds' if row['interval_holds'] else 'MISSES'}")

    if not rows:
        print("no captures found", file=sys.stderr)
        return 2

    ok = [r for r in rows if "footprint_error_pct" in r]
    failed = [r for r in rows if "video_failed" in r]
    if not ok:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"rows": rows, "conclusion":
                                   "the video tier produced no usable plan on any capture"},
                                  indent=2) + "\n")
        print("\n  the video tier produced no usable plan on any capture")
        return 0
    errs = np.array([abs(r["footprint_error_pct"]) / 100 for r in ok])
    # The factor that would have put every reference inside its interval. The base sigma on a
    # footprint is 4% of the value (pipeline.AREA_RELATIVE_SIGMA), so the half-width is
    # Z90 * 0.04 * factor and the factor needed is err / (Z90 * 0.04).
    needed = errs / (Z90 * 0.04)
    recommended = float(np.ceil(needed.max() * 2) / 2)

    result = {
        "note": "the LiDAR result is the reference, not ground truth; there is no tape or laser "
                "truth for these captures, so this measures agreement between tiers",
        "rows": rows,
        "shipped_widening_factor": 11.0,
        "factor_needed_per_capture": [round(float(x), 2) for x in needed],
        "recommended_widening_factor": recommended,
        "intervals_holding_at_shipped_factor": sum(r.get("interval_holds", False) for r in ok),
        "captures_attempted": len(rows),
        "captures_where_video_failed": len(failed),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    print(f"\n  footprint error: median {np.median(errs)*100:.1f}%, worst {errs.max()*100:.1f}%")
    print(f"  video produced a plan on {len(ok)}/{len(rows)} captures")
    print(f"  intervals holding at the shipped factor: "
          f"{result['intervals_holding_at_shipped_factor']}/{len(ok)}")
    print(f"  factor needed per capture: {[round(float(x),1) for x in needed]}")
    print(f"  RECOMMENDED widening factor: x{recommended}")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
