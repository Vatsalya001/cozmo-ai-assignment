"""The committed document PDFs, and the page caps two of them claim.

Why these are tests and not a line in a README: the brief caps the technical report at six
pages and `docs/capture_protocol.md` calls itself "one page" in its own title. Both are claims
about a rendered artifact, and a claim about a rendered artifact can only be checked by
rendering it. Until this file existed, `docs/compliance_matrix.md` carried D.7 as **Met** and
nothing had ever counted the pages.

Page counts here are read back out of the PDF bytes, not taken from the renderer's own
pagination -- a cap checked against the tool's intent rather than its output is not checked.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mdpdf import count_pdf_pages                                      # noqa: E402
import render_docs_pdf                                                 # noqa: E402

PDF_DIR = ROOT / "submission" / "docs"
EXPECTED = [(Path(rel), cap) for rel, cap in render_docs_pdf.DOCUMENTS]


@pytest.mark.parametrize("rel,cap", EXPECTED, ids=[p.stem for p, _ in EXPECTED])
def test_every_key_document_has_a_committed_pdf(rel, cap):
    """A reviewer on a tablet, or holding a printed pack, should not be handed markdown."""
    assert (ROOT / rel).is_file(), f"{rel} is in the render list but not in the repo"
    pdf = PDF_DIR / (rel.stem + ".pdf")
    assert pdf.is_file(), (
        f"{pdf.relative_to(ROOT)} is missing. Run: python scripts/render_docs_pdf.py")
    assert pdf.stat().st_size > 2000, f"{pdf.name} is too small to be a rendered document"
    assert count_pdf_pages(pdf) >= 1


def test_the_technical_report_fits_the_briefs_six_page_cap():
    """The brief's limit. If this fails the document is too long -- shorten it.

    Do not reach for the type sizes in `scripts/mdpdf/layout.py`: shrinking the font to slide
    under a page cap is the same dishonesty as tuning a constant until a gate goes green. For
    the record, the measurement is not a property of this renderer. Chrome, laying out the same
    blocks at the same sizes, also gives 8 pages, and the report only reaches 6 at a 7 pt body
    on 13 mm margins, which is not a size anyone should be asked to read.
    """
    pages = count_pdf_pages(PDF_DIR / "technical_report.pdf")
    assert pages <= 6, (
        f"docs/technical_report.md renders {pages} A4 pages against the brief's cap of 6. "
        f"Cut {pages - 6} page(s) of content; do not shrink the type.")


def test_the_capture_protocol_is_the_one_page_its_title_claims():
    """`# Capture protocol -- one page`. The whole point is that it is handed to a
    non-engineer, and a protocol that runs onto a second page gets its second page lost."""
    pages = count_pdf_pages(PDF_DIR / "capture_protocol.pdf")
    assert pages == 1, (
        f"docs/capture_protocol.md calls itself one page and renders {pages}. "
        f"Either shorten it or change the title.")


@pytest.mark.parametrize("rel,cap", [(p, c) for p, c in EXPECTED if c is not None],
                         ids=[p.stem for p, c in EXPECTED if c is not None])
def test_the_committed_pdf_is_what_the_markdown_renders_to_today(rel, cap, tmp_path):
    """A committed artifact that has drifted from its source is worse than no artifact: it
    reads as current. The renderer omits the PDF creation date for exactly this reason, so an
    unchanged document re-renders byte-for-byte and a changed one does not.

    Only the two capped documents are re-rendered here; checking all six would add about 30 s
    to the suite to catch the same class of staleness.
    """
    from mdpdf import render
    fresh = tmp_path / (rel.stem + ".pdf")
    render(ROOT / rel, fresh, label=f"{rel.as_posix()}  ·  scanplan submission")
    committed = PDF_DIR / (rel.stem + ".pdf")
    assert fresh.read_bytes() == committed.read_bytes(), (
        f"{committed.relative_to(ROOT)} is stale against {rel}. "
        f"Run: python scripts/render_docs_pdf.py")


def test_the_compliance_matrix_does_not_claim_a_page_cap_it_misses():
    """D.7 asserted **Met** for 'Technical report, max 6 pages' while the report was eight
    pages, because nobody had rendered it. Whatever the status says, it has to agree with the
    PDF -- that is the only part of this a reviewer cannot check for themselves in a second."""
    row = next(line for line in (ROOT / "docs" / "compliance_matrix.md").read_text().splitlines()
               if line.startswith("| D.7 "))
    over_cap = count_pdf_pages(PDF_DIR / "technical_report.pdf") > 6
    claims_met = "**Met**" in row
    assert not (over_cap and claims_met), (
        "compliance_matrix.md D.7 claims the 6-page cap is Met, but "
        "submission/docs/technical_report.pdf is over it:\n  " + row.strip())
    assert not (not over_cap and not claims_met), (
        "the report is now within the cap; D.7 should say Met:\n  " + row.strip())
