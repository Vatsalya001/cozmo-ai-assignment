"""One command per capture, as the brief requires.

    scanplan run <Stray Scanner folder | video.mov | folder of room photo folders>

The tier is detected from the input. Every run writes result.json (schema-validated),
plan.svg, summary.md and report.pdf.

The pipeline stages are stubs at this commit; the contract, the validator and the CLI shape
come first so that every later stage has a validated place to write into.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .detect import CaptureError, detect_tier
from .validate import validate, validate_file


def _stub_result(capture_id: str, tier: str, source: Path, runtime_s: float) -> dict:
    """A minimal document that satisfies the contract. Replaced stage by stage as the
    geometry lands; keeping it valid from commit one means the export path is never the
    thing that breaks on the walk-in day."""
    return {
        "schema_version": "0.1.0",
        "units": "m",
        "capture": {
            "id": capture_id,
            "tier": tier,
            "source_path": str(source),
            "pipeline_version": __version__,
            "runtime_s": round(runtime_s, 2),
            "drift_correction": False,
        },
        "rooms": [],
        "plan": {"footprint_m2": unobserved(0.0, 2.0, method="not yet implemented").as_dict(),
                 "adjacency": [], "groups": 0},
        "damage": [],
        "concealed_flags": [],
        "scope": [],
        "quality": {"warnings": [
            {"code": "PIPELINE_STUB", "severity": "error",
             "message": "geometry stages are not implemented at this commit; no measurement here is real"}
        ]},
    }


def cmd_inspect(args) -> int:
    path = Path(args.path)
    tier = detect_tier(path)
    print(json.dumps({"path": str(path), "tier": tier}, indent=2))
    return 0


def cmd_run(args) -> int:
    source = Path(args.path)
    started = time.perf_counter()
    tier = detect_tier(source)

    from . import pipeline
    result = pipeline.run(source, tier=tier, drift=not args.no_drift, damage=not args.no_damage)

    problems = validate(result)
    if problems:
        print("error: the result does not satisfy its own schema:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else Path("out") / (source.stem or source.name)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    from .export import render
    written = ["result.json"] + render.write_all(result, out)

    fp = result["plan"]["footprint_m2"]
    print(f"{source}: {tier} tier, {len(result['rooms'])} rooms, "
          f"footprint {fp['value']:.2f} m2 [{fp['ci_low']:.2f}, {fp['ci_high']:.2f}], "
          f"{result['capture']['runtime_s']} s")
    for w in result["quality"]["warnings"]:
        print(f"  {w['severity']}: {w['message']}")
    print(f"wrote {out}/: {', '.join(written)}")
    return 0


def cmd_validate(args) -> int:
    problems = validate_file(args.path)
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return 1
    print(f"{args.path}: valid")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="scanplan", description="Measured floor plans from phone captures.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="detect a capture's tier and summarise it")
    p.add_argument("path")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("run", help="measure a capture: writes result.json, plan.svg, summary.md, report.pdf")
    p.add_argument("path", help="Stray Scanner folder, video file, or folder of room photo folders")
    p.add_argument("--out", help="output folder (default: out/<capture name>)")
    p.add_argument("--no-drift", action="store_true", help="skip drift correction (the G-DRIFT ablation)")
    p.add_argument("--no-damage", action="store_true", help="skip damage detection")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("validate", help="check a result file against the schema")
    p.add_argument("path")
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CaptureError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 -- deliberate
        # The walk-in test is a live cold run in front of the examiners. A traceback there is
        # worth less than a stated failure, so unexpected errors are reported and the full
        # trace is kept behind SCANPLAN_TRACEBACK=1 for our own debugging.
        import os
        if os.environ.get("SCANPLAN_TRACEBACK"):
            raise
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        print("  (set SCANPLAN_TRACEBACK=1 for the full trace)", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
