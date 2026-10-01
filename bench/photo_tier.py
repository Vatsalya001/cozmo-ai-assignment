"""Photo tier on per-room folders, recorded for the gate table.

There is no reference for these folders -- they are cut from a supplied capture's RGB stream,
and nobody has tape-measured that property. So this records what the tier produces and how it
is grouped, which is enough to settle G-PHOTO-STITCH, and explicitly does not claim an
accuracy number it cannot support.

The input is built by scripts/build_photoset.py at fixed frame indices, and is rebuilt here if
absent. It used to default to a hand-made /tmp/photoset, which was cleaned up -- leaving the
photo tier's only committed benchmark resting on an input that existed nowhere. See that
script's docstring for what a segment of a walk may and may not be claimed to be.
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scanplan import pipeline                                     # noqa: E402
from scripts.build_photoset import CAPTURE, DEFAULT_OUT, build    # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
OUT = ROOT / "bench" / "results" / "photo_tier.json"

if not (FOLDER.is_dir() and any(FOLDER.glob("*/*.jpg"))):
    print(f"photo set absent at {FOLDER}; building it from {CAPTURE.name}")
    build(CAPTURE, FOLDER)

t0 = time.perf_counter()
doc = pipeline.run(FOLDER)
fp = doc["plan"]["footprint_m2"]
res = {
    # Repo-relative: an absolute path differs on every machine and would make this file
    # disagree with itself in the clean-clone check for no reason that is about the result.
    "source": str(FOLDER.resolve().relative_to(ROOT)) if FOLDER.resolve().is_relative_to(ROOT)
              else FOLDER.name,
    "rooms": len(doc["rooms"]), "groups": doc["plan"]["groups"],
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
