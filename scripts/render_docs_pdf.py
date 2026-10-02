"""Render the key documents to PDFs in submission/docs/, and check the declared page caps.

A reviewer who reads on a tablet or prints the pack gets markdown source otherwise. These are
small, so they are committed alongside the rest of the submission bundle.

Two of the caps are claims the brief or a document makes, so they are checked here rather than
asserted in prose:

    technical_report.md    at most 6 pages   (the brief's limit)
    capture_protocol.md    1 page            ("one page", in its own title)

Over-cap exits non-zero and names the overrun. The fix for an overrun is a shorter document,
never a smaller font -- the type sizes in mdpdf/layout.py are fixed by readability.

An unchanged document re-renders byte-for-byte -- the PDF creation date is deliberately omitted
-- so `tests/test_docs_pdf.py` can tell a committed PDF that is current from one that is stale.

    python scripts/render_docs_pdf.py                           # render all, enforce caps
    python scripts/render_docs_pdf.py docs/gates.md             # one file, no cap
    python scripts/render_docs_pdf.py docs/gates.md --cap 2     # one file, with a cap
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mdpdf import count_pdf_pages, render, text                       # noqa: E402

OUT_DIR = ROOT / "submission" / "docs"

# (document, page cap or None). Order is the order to read them in.
DOCUMENTS: list[tuple[str, int | None]] = [
    ("docs/technical_report.md", 6),          # the brief's cap
    ("docs/capture_protocol.md", 1),          # the document's own claim, in its title
    ("docs/compliance_matrix.md", None),
    ("docs/fix_loop_declaration.md", None),
    ("docs/walk_in.md", None),
    ("docs/declined_changes.md", None),
]


def render_one(rel: str, cap: int | None) -> tuple[str, int, int | None, bool]:
    src = ROOT / rel
    out = OUT_DIR / (src.stem + ".pdf")
    pages = render(src, out, label=f"{rel}  ·  scanplan submission")
    return rel, pages, cap, cap is None or pages <= cap


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
    print(f"\n{len(results)} documents, {total} pages, written to "
          f"{OUT_DIR.relative_to(ROOT) if OUT_DIR.is_relative_to(ROOT) else OUT_DIR}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
