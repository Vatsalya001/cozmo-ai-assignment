"""Download HouseLayout3D into data/external/houselayout3d/ (gitignored).

    python scripts/fetch_houselayout3d.py

About 56 MB: 16 Matterport3D buildings as planar layout entities, plus door, window and stair
annotations. MIT licence. Only `structures/layouts_split_by_entity/` and `doors/` are needed by
bench/houselayout_adjacency.py; the whole snapshot is taken anyway so the provenance is one
command rather than a file list. Re-running skips what is already there.

The Hub rate-limits anonymous resolver calls at 5000 per 5 minutes and this snapshot is ~4800
files, so a cold fetch occasionally stops with HTTP 429. Re-run it; the cache keeps what
arrived.

The revision is PINNED. `bench/results/houselayout_adjacency.json` is a 16k-line artifact that
`bench/clean_clone_check.sh` regenerates from a clean clone and compares field by field against
the committed copy, and every number in it is read out of this snapshot. Left on the default
branch, an upstream re-upload -- one re-exported mesh, one corrected door rectangle -- would
turn that check into DIFFERS and exit non-zero, and the failure would look like a bug in our
code rather than a moved dataset. REVISION is the
commit the committed result file was generated from; it is recorded in the download metadata
under `.cache/huggingface/download/*.metadata` in any directory this script has filled.
"""
from __future__ import annotations

import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "external" / "houselayout3d"
REPO = "houselayout3d/HouseLayout3D"
REVISION = "c9c483e2890293230273f1ed475fd286e3b6cb39"


def main() -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("pip install huggingface_hub")
    snapshot_download(repo_id=REPO, repo_type="dataset", revision=REVISION,
                      local_dir=str(OUT), max_workers=4)
    n = len(list((OUT / "structures" / "layouts_split_by_entity").glob("*/*.ply")))
    print(f"{OUT}: {n} layout entities, {len(list((OUT / 'doors').glob('*.json')))} door files")


if __name__ == "__main__":
    main()
