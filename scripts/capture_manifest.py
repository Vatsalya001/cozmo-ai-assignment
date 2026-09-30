"""Checksum the captures, and check them again later.

This exists because it already bit us. The first extraction of the supplied zips silently
produced three corrupt PNGs -- the archives verified fine, but bytes on disk did not match
them, and one file read clean in one pass and failed in the next. A benchmark run over
quietly damaged input produces numbers that look perfectly reasonable and are wrong.

    python scripts/capture_manifest.py data/captures            # write the manifest
    python scripts/capture_manifest.py data/captures --check    # verify against it

Run --check before any benchmark whose numbers you intend to report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST = Path("data/captures_manifest.json")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def scan(root: Path) -> dict:
    out = {}
    for capture in sorted(d for d in root.iterdir() if d.is_dir()):
        files = sorted(f for f in capture.rglob("*") if f.is_file())
        out[capture.name] = {
            "files": len(files),
            "bytes": sum(f.stat().st_size for f in files),
            # One digest over the whole capture: cheaper to store than 33,000 rows, and it
            # answers the only question that matters -- did anything change?
            "sha256": hashlib.sha256(
                "".join(f"{f.relative_to(capture)}:{digest(f)}" for f in files).encode()
            ).hexdigest(),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--check", action="store_true", help="verify against the stored manifest")
    args = ap.parse_args()

    current = scan(args.root)

    if not args.check:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(current, indent=2) + "\n")
        for name, m in current.items():
            print(f"{name}: {m['files']} files, {m['bytes']/1e6:.0f} MB, {m['sha256'][:16]}")
        print(f"wrote {MANIFEST}")
        return 0

    if not MANIFEST.is_file():
        print(f"error: {MANIFEST} does not exist; run without --check first", file=sys.stderr)
        return 2

    stored = json.loads(MANIFEST.read_text())
    failed = False
    for name, m in stored.items():
        got = current.get(name)
        if got is None:
            print(f"MISSING  {name}", file=sys.stderr); failed = True
        elif got["sha256"] != m["sha256"]:
            print(f"CHANGED  {name}: {got['files']} files vs {m['files']} expected", file=sys.stderr)
            failed = True
        else:
            print(f"ok       {name}")
    for name in current.keys() - stored.keys():
        print(f"UNKNOWN  {name} is not in the manifest")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
