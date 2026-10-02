"""Render the key documents to PDFs in submission/docs/, and check the declared page caps.

A reviewer who reads on a tablet or prints the pack gets markdown source otherwise. These are
small, so they are committed alongside the rest of the submission bundle.

Two of the caps are claims the brief or a document makes, so they are checked here rather than
asserted in prose:

    technical_report.md    at most 6 pages   (the brief's limit)
    capture_protocol.md    1 page            ("one page", in its own title)

Over-cap exits non-zero and names the overrun. The fix for an overrun is a shorter document,
never a smaller font -- the type sizes in mdpdf/layout.py are fixed by readability.

## Provenance, stated accurately

**The idea is not mine.** Rendering the submission documents to PDF *and asserting the page
cap in the same script* is the report-PDF script of an independent submission to the same brief
-- the same submission from which this project's other borrowed work is credited
(`bench/same_flat.py`, `bench/wall_normals.py`). Theirs is
61 lines around headless Chrome and `markdown`; `scripts/mdpdf/` is an independent ~940-line
layout engine on matplotlib and fontTools, written that way because the walk-in test is a cold
run on a machine we do not control and "install a headless browser first" is not a thing to say
in front of examiners. So the implementations share nothing, but the move -- render it, count
the pages, exit non-zero -- is theirs, and this project had carried compliance-matrix D.7 as
**Met** for a cap nobody had ever counted.

Two smaller debts in the same direction:

* The **8.9 pt body on 13 mm margins** quoted in the sensitivity sweep behind D.7, used to show
  that the report's overrun was content rather than layout, is their print CSS, not a geometry
  this repo ever shipped.
* The table-header fill `HEAD_FILL = "#eef0f3"` in `mdpdf/layout.py` is their
  `th { background: #eef0f3 }`. Cosmetic, and it appears nowhere else in this repo, so it is
  credited rather than left to be found.

## Staleness of the committed PDFs

A committed artifact that has drifted from its source is worse than no artifact: it reads as
current. The PDF creation date is deliberately omitted, so re-rendering unchanged markdown on
*this* matplotlib gives a byte-identical file -- but matplotlib's PDF output is not stable
across versions, and a cold clone is exactly the case these PDFs exist to serve. So the check
that a reviewer's clone runs is version-independent: `render_manifest.json` records, for all six
documents, a digest of the *parsed markdown* and a digest of the *committed PDF*, and
`tests/test_docs_pdf.py` recomputes both. A byte-for-byte comparison is run as well, but only
when the recorded matplotlib version matches the installed one.

    python scripts/render_docs_pdf.py                           # render all, enforce caps
    python scripts/render_docs_pdf.py docs/gates.md             # one file, no cap
    python scripts/render_docs_pdf.py docs/gates.md --cap 2     # one file, with a cap
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
from fontTools import version as fonttools_version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mdpdf import count_pdf_pages, file_digest, render, structure_digest, text   # noqa: E402

OUT_DIR = ROOT / "submission" / "docs"
MANIFEST_NAME = "render_manifest.json"

# (document, page cap or None). Order is the order to read them in.
DOCUMENTS: list[tuple[str, int | None]] = [
    ("docs/technical_report.md", 6),          # the brief's cap
    ("docs/capture_protocol.md", 1),          # the document's own claim, in its title
    ("docs/compliance_matrix.md", None),
    ("docs/fix_loop_declaration.md", None),
    ("docs/walk_in.md", None),
    ("docs/declined_changes.md", None),
]


def label_for(rel: str) -> str:
    """The footer line. Part of the render input, so the manifest's digests depend on it."""
    return f"{rel}  ·  scanplan submission"


def render_one(rel: str, cap: int | None) -> tuple[str, int, int | None, bool]:
    src = ROOT / rel
    out = OUT_DIR / (src.stem + ".pdf")
    pages = render(src, out, label=label_for(rel))
    return rel, pages, cap, cap is None or pages <= cap


def write_manifest(results: list[tuple[str, int, int | None, bool]]) -> Path:
    """Record what was rendered, from what, and on which matplotlib.

    Every document gets an entry, not only the two with page caps: a compliance matrix whose
    PDF has quietly drifted from its markdown misleads a reviewer exactly as much as a stale
    technical report would, and the markdown digest costs a parse rather than a render.
    """
    manifest = {
        "written_by": "scripts/render_docs_pdf.py",
        "matplotlib": matplotlib.__version__,
        "fonttools": fonttools_version,
        "note": ("markdown_sha256 is a digest of the parsed blocks -- the whole render input. "
                 "pdf_sha256 is of the committed file. Both are version-independent; a "
                 "byte-for-byte re-render is only expected on the matplotlib recorded here."),
        "documents": {},
    }
    for rel, pages, cap, _ in results:
        pdf = OUT_DIR / (Path(rel).stem + ".pdf")
        manifest["documents"][rel] = {
            "pdf": f"submission/docs/{pdf.name}",
            "pages": pages,
            "cap": cap,
            "markdown_sha256": structure_digest(ROOT / rel),
            "pdf_sha256": file_digest(pdf),
            "pdf_bytes": pdf.stat().st_size,
        }
    path = OUT_DIR / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="markdown files to render instead of the default set")
    ap.add_argument("--cap", type=int, default=None, help="page cap for an explicit path")
    ap.add_argument("--out", default=None, help="output directory (default submission/docs)")
    args = ap.parse_args(argv)

    global OUT_DIR
    if args.out:
        OUT_DIR = Path(args.out).resolve()
    wanted = [(p, args.cap) for p in args.paths] if args.paths else DOCUMENTS

    results = [render_one(rel, cap) for rel, cap in wanted]

    width = max(len(r[0]) for r in results)
    print(f"{'document':<{width}}  pages  cap    size")
    for rel, pages, cap, ok in results:
        out = OUT_DIR / (Path(rel).stem + ".pdf")
        kb = out.stat().st_size / 1024
        flag = "" if ok else "  OVER CAP"
        print(f"{rel:<{width}}  {pages:>5}  {cap if cap else '-':<5}  {kb:>5.0f} KB{flag}")

    if text.unmapped:
        names = ", ".join(f"U+{ord(c):04X}" for c in sorted(text.unmapped))
        print(f"\nnot in DejaVu, drawn as '?': {names}", file=sys.stderr)

    over = [(rel, pages, cap) for rel, pages, cap, ok in results if not ok]
    for rel, pages, cap in over:
        print(f"\nOVER CAP: {rel} renders {pages} pages against a cap of {cap}. "
              f"Shorten the document; do not shrink the type.", file=sys.stderr)
    total = sum(count_pdf_pages(OUT_DIR / (Path(r[0]).stem + ".pdf")) for r in results)
    print(f"\n{len(results)} documents, {total} pages, "
          f"{sum(f['pdf_bytes'] for f in _sizes(results)):,} bytes, written to "
          f"{OUT_DIR.relative_to(ROOT) if OUT_DIR.is_relative_to(ROOT) else OUT_DIR}")

    # Only the full default set describes the committed state, so only it rewrites the manifest.
    if wanted is DOCUMENTS:
        print(f"manifest: {write_manifest(results).relative_to(ROOT)}")
    else:
        print(f"(subset render: {MANIFEST_NAME} left alone)")
    return 1 if over else 0


def _sizes(results) -> list[dict]:
    return [{"pdf_bytes": (OUT_DIR / (Path(r[0]).stem + ".pdf")).stat().st_size} for r in results]


if __name__ == "__main__":
    sys.exit(main())
