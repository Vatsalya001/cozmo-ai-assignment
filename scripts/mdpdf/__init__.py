"""Markdown to a paged A4 PDF, using only what this repo already installs.

The pack is read on a tablet or printed, and markdown on disk serves neither. So the key
documents get rendered. The renderer is matplotlib and fontTools — both already hard
dependencies — for the same reason `scanplan/export/report.py` is: the walk-in test is a cold
run on a machine we do not control, and "install a headless browser first" is not a thing to
say in front of examiners. `reportlab`, `weasyprint` and `markdown` are all absent from this
environment and none of them would buy anything the six documents need.

What it gives up by not being a browser: no CSS, no hyphenation, no float layout, and a
deliberately small markdown subset (see `blocks.py`). What it buys: exact font metrics from the
same TTF matplotlib draws with, so page counts are arithmetic rather than a screenshot.

    from mdpdf import render, count_pdf_pages
    pages = render(Path("docs/capture_protocol.md"), Path("out/capture_protocol.pdf"))
"""
from __future__ import annotations

import re
from pathlib import Path

from . import blocks, layout, text

__all__ = ["render", "count_pdf_pages", "A4_POINTS", "blocks", "layout", "text"]

A4_POINTS = (layout.PAGE_W, layout.PAGE_H)


def render(src: Path, out_pdf: Path, *, label: str | None = None) -> int:
    """Render one markdown file. Returns the page count of the file on disk.

    The return value is read back out of the written PDF rather than taken from the paginator,
    so the number reported is the number a reviewer's PDF viewer will show.
    """
    src, out_pdf = Path(src), Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = blocks.parse(src.read_text())
    pages = layout.paginate(layout.flow(doc))
    laid_out = layout.paint(pages, out_pdf, label or src.name)
    on_disk = count_pdf_pages(out_pdf)
    if on_disk != laid_out:
        raise AssertionError(
            f"{out_pdf}: laid out {laid_out} pages but the file contains {on_disk}")
    return on_disk


_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![s/\w])")
_PAGE_COUNT = re.compile(rb"/Type\s*/Pages\b.{0,200}?/Count\s+(\d+)", re.S)


def count_pdf_pages(path: Path) -> int:
    """Count pages by reading the PDF, not by trusting whatever wrote it.

    A page cap that is checked against the renderer's own intent is not checked at all. This
    counts `/Type /Page` objects in the file and cross-checks them against the `/Count` on the
    page-tree node; the two disagreeing means the file is malformed, which is worth a loud
    failure rather than a plausible number.
    """
    raw = Path(path).read_bytes()
    objects = len(_PAGE_OBJECT.findall(raw))
    declared = [int(m.group(1)) for m in _PAGE_COUNT.finditer(raw)]
    if not objects:
        raise ValueError(f"{path}: no page objects found; not a PDF this counter understands")
    if declared and max(declared) != objects:
        raise ValueError(f"{path}: {objects} page objects but /Count says {max(declared)}")
    return objects
