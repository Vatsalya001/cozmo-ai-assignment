"""Fetch the BD3 building-defect image dataset, for bench/damage_appearance.py only.

    pip install -e '.[damage]'              # pandas + pyarrow + sklearn; required first
    python scripts/fetch_bd3.py            # ~800 MB of parquet into data/external/bd3
    python scripts/fetch_bd3.py --check     # report what is already local, download nothing

## What this is for

`bench/damage_appearance.py` answers one question -- can a defect class be NAMED from
appearance alone -- and it needs labelled photographs of real building defects to answer it.
BD3 (Building Defect Detection Dataset) publishes 3,965 512x512 crops over seven labels:
`algae`, `major_crack`, `minor_crack`, `peeling`, `spalling`, `stain`, `plain`. Six map onto
the damage-class enum in `schema/output.schema.json`; `plain` is the negative/reject class.

The HuggingFace re-release stores them as three parquet files with columns `image` (a struct
of JPEG bytes), `question` (a constant string, carrying no information) and `answer` (the
label). Those files are what this script fetches.

## LICENCE POSITION -- read this before reusing anything here

The re-release's YAML metadata is tagged `license: cc-by-4.0`. That tag does not survive
contact with the chain behind it, and all three links were checked rather than assumed:

1. **The re-release's own card contradicts its own tag.** Under "License" it says *"This
   dataset follows the same license as the original BD3 dataset. Please check the original
   source before using it for commercial purposes."* It also states *"All image rights and
   original credit belong to the original authors"*. So the uploader is deferring upstream,
   not granting CC-BY -- the `cc-by-4.0` tag is contradicted by the prose beneath it.
2. **Upstream states no licence.** The original is BD3 (Kottari & Arjunan, 2024),
   `github.com/Praveenkottari/BD3-Dataset`. The GitHub API reports `license: null` for that
   repository and its `/license` endpoint returns 404 -- there is no licence file to follow.
3. **So the deferral terminates nowhere.** The tag points at a licence the upstream never
   granted, and a permissive tag applied downstream cannot create rights that do not exist
   upstream.

This project therefore treats the images as **licence-unknown** and acts on it:

- **The images are not redistributed.** They land in `data/external/`, which is gitignored.
  Nothing fetched here enters the repository or the submission bundle.
- **No trained weight file is committed.** Weights fitted on these images are arguably a
  derivative work of images whose licence is unknown, so `bench/damage_appearance.py` has no
  `--save-model` flag and ships no `.pkl`, `.joblib` or `.npz` of model parameters. It
  **trains at run time** from the locally fetched data and publishes only measured numbers,
  which are facts about the data rather than copies of it.
- **The shipped pipeline therefore gains no appearance classifier.** What ships is a measured
  benchmark of the capability plus the statement that it is not wired in. That is the honest
  deliverable and `bench/results/damage_appearance.json` says so in
  `what_this_does_not_close`.

If BD3's authors publish a licence, the second and third bullets are the ones to revisit; the
first is already the correct default for any fetched dataset in this repo. Cite the original
either way:

    Kottari, Praveen and Arjunan, Pandarasamy. BD3: Building Defect Dataset, 2024.
    https://github.com/Praveenkottari/BD3-Dataset

## What this does NOT give you

Not a staged room, so it does not satisfy `A-DMG-DETECT`. Not a test of the geometric damage
detector in `scanplan`, which finds departures from a fitted wall plane and is indifferent to
colour. Not detection or localisation -- every image is already cropped to its defect. See
`bench/results/damage_appearance.json` for the full list.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "bd3" / "data"

REPO = "chandrabhuma/building_defect_vqa"
# Pinned: the revision the committed benchmark numbers were measured on. `main` would let the
# dataset move under a result file that claims to describe it.
REVISION = "520fef082f3b2bf42d5301f885079f74bac839de"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/data"
UPSTREAM = "https://github.com/Praveenkottari/BD3-Dataset"
FILES = [
    "test-00000-of-00001.parquet",
    "train-00000-of-00002.parquet",
    "train-00001-of-00002.parquet",
]
EXPECTED_ROWS = {"test": 793, "train": 3172}

LICENCE = (
    "licence-unknown. The HF re-release is TAGGED cc-by-4.0 but its own card defers upstream "
    "('follows the same license as the original BD3 dataset', 'all image rights belong to the "
    f"original authors'), and upstream ({UPSTREAM}) has NO licence file -- GitHub reports "
    "license: null and its /license endpoint 404s. The deferral terminates nowhere, so: images "
    "are not redistributed (data/external/ is gitignored) and NO trained weights are committed."
)


def download(url: str, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size > 0:
        print(f"    {dst.name}: already local ({dst.stat().st_size/1e6:.0f} MB)")
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("content-length", 0))
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {dst.name}: {done/1e6:.0f}/{total/1e6:.0f} MB", end="", flush=True)
    print()
    tmp.rename(dst)
    return dst


def require_parquet_engine() -> None:
    """Fail in one second rather than after ~800 MB.

    `summarise()` runs AFTER the download loop, and `pandas.read_parquet` raises a bare
    "Unable to find a usable engine" when no parquet engine is installed. pandas does not
    declare one, and nothing else in this project pulls one in transitively -- so on a clean
    `pip install -e '.[dev]'` the whole fetch completed and *then* crashed. Both dependencies
    live in the `[damage]` extra; this check is called before the first byte is downloaded.
    """
    for mod, hint in (("pandas", "pandas"), ("pyarrow", "pyarrow (the parquet engine)")):
        try:
            __import__(mod)
        except ImportError:
            raise SystemExit(
                f"{hint} is missing, and scripts/fetch_bd3.py reads BD3's parquet files.\n"
                f"    install it first:  pip install -e '.[damage]'\n"
                f"    (checked before the ~800 MB download, not after it)")


def summarise() -> list[dict]:
    """Row counts and label histograms per file. Needs pandas + pyarrow, both in the
    `[damage]` extra; `require_parquet_engine()` has already proved they are importable."""
    import pandas as pd

    rows = []
    for name in FILES:
        path = OUT / name
        if not path.is_file():
            rows.append({"file": name, "present": False})
            continue
        df = pd.read_parquet(path, columns=["answer"])
        rows.append({
            "file": name,
            "present": True,
            "fold": "test" if name.startswith("test") else "train",
            "rows": len(df),
            "labels": {str(k): int(v) for k, v in df["answer"].value_counts().items()},
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report local state, download nothing")
    args = ap.parse_args()

    print(f"BD3 -> {OUT.relative_to(ROOT)}")
    print(f"licence: {LICENCE}\n")

    # Before the download loop, not after it: the summary step needs a parquet engine either
    # way, and discovering that at the end costs the reviewer the entire ~800 MB fetch.
    require_parquet_engine()

    if not args.check:
        for name in FILES:
            try:
                download(f"{BASE}/{name}", OUT / name)
            except urllib.error.HTTPError as e:
                print(f"    {name}: HTTP {e.code} -- the re-release may have moved; the dataset "
                      f"is not required for the main test suite", file=sys.stderr)
                return 1

    rows = summarise()
    missing = [r["file"] for r in rows if not r["present"]]
    if missing:
        print(f"\nmissing: {missing}")
        return 1

    per_fold: dict[str, int] = {}
    for r in rows:
        per_fold[r["fold"]] = per_fold.get(r["fold"], 0) + r["rows"]
        print(f"  {r['file']}: {r['rows']} rows ({r['fold']})")
    print(f"\ntotals: {per_fold} ({sum(per_fold.values())} images)")

    for fold, want in EXPECTED_ROWS.items():
        got = per_fold.get(fold, 0)
        if got != want:
            print(f"WARNING: {fold} fold has {got} rows, expected {want}. The re-release may "
                  f"have been revised; bench/damage_appearance.py reports whatever it finds, so "
                  f"re-run it and the committed numbers will move.", file=sys.stderr)

    (OUT.parent / "fetch_manifest.json").write_text(json.dumps(
        {"repo": REPO, "licence_position": LICENCE, "files": rows, "totals": per_fold},
        indent=2) + "\n")
    print("\nnext: python bench/damage_appearance.py   (trains at run time, ships no weights)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
