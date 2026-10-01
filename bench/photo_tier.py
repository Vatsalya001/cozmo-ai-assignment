"""Photo tier on per-room folders, recorded for the gate table.

There is no reference for these folders -- they are cut from a supplied capture's RGB stream,
and nobody has tape-measured that property. So this records what the tier produces and how it
is grouped, which is enough to settle G-PHOTO-STITCH, and explicitly does not claim an
accuracy number it cannot support.
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scanplan import pipeline                                     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/photoset")
OUT = ROOT / "bench" / "results" / "photo_tier.json"

t0 = time.perf_counter()
doc = pipeline.run(FOLDER)
fp = doc["plan"]["footprint_m2"]
res = {
    "source": str(FOLDER), "rooms": len(doc["rooms"]), "groups": doc["plan"]["groups"],
    "footprint_m2": fp["value"], "ci": [fp["ci_low"], fp["ci_high"]],
    "widening_factor": doc["quality"]["interval_widening_factor"],
    "runtime_s": round(time.perf_counter() - t0, 1),
    "per_room": [{"label": r["label"], "area_m2": r["floor_area_m2"]["value"]}
                 for r in doc["rooms"]],
    "note": "no reference exists for these folders; stitch grouping is the measurable outcome",
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(res, indent=2) + "\n")
print(json.dumps(res, indent=2))
