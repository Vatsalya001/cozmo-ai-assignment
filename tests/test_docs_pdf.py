"""The committed document PDFs, and the page caps two of them claim.

Why these are tests and not a line in a README: the brief caps the technical report at six
pages and `docs/capture_protocol.md` calls itself "one page" in its own title. Both are claims
about a rendered artifact, and a claim about a rendered artifact can only be checked by
rendering it. Until this file existed, `docs/compliance_matrix.md` carried D.7 as **Met** and
nothing had ever counted the pages.

Page counts here are read back out of the PDF bytes, not taken from the renderer's own
pagination -- a cap checked against the tool's intent rather than its output is not checked.

Staleness is checked in two layers, because matplotlib's PDF writer is not byte-stable across
versions and `pyproject.toml` pins only `matplotlib>=3.7`:

* **Version-independent, runs everywhere** -- the digest of the parsed markdown and the digest
  of the committed PDF are both recomputed against `submission/docs/render_manifest.json`. This
  covers all six documents, so a drifted compliance-matrix PDF fails too.
* **Byte-for-byte** -- a fresh render is compared to the committed bytes, but only on the
  matplotlib version the manifest records. On any other version it skips with that reason,
  rather than reporting "is stale" about a file that is current. A cold clone is the exact case
  these PDFs exist to serve (`bench/clean_clone_check.sh` measures it), so a check that fails
  there on a version difference would be noise where a real signal has to live.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import matplotlib
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mdpdf import count_pdf_pages, file_digest, structure_digest                # noqa: E402
import render_docs_pdf                                                         # noqa: E402

PDF_DIR = ROOT / "submission" / "docs"
MANIFEST = PDF_DIR / render_docs_pdf.MANIFEST_NAME
EXPECTED = [(Path(rel), cap) for rel, cap in render_docs_pdf.DOCUMENTS]
RERENDER = "Run: python scripts/render_docs_pdf.py"


def manifest() -> dict:
    assert MANIFEST.is_file(), f"{MANIFEST.relative_to(ROOT)} is missing. {RERENDER}"
    return json.loads(MANIFEST.read_text())


@pytest.mark.parametrize("rel,cap", EXPECTED, ids=[p.stem for p, _ in EXPECTED])
def test_every_key_document_has_a_committed_pdf(rel, cap):
    """A reviewer on a tablet, or holding a printed pack, should not be handed markdown."""
    assert (ROOT / rel).is_file(), f"{rel} is in the render list but not in the repo"
    pdf = PDF_DIR / (rel.stem + ".pdf")
    assert pdf.is_file(), f"{pdf.relative_to(ROOT)} is missing. {RERENDER}"
    assert pdf.stat().st_size > 2000, f"{pdf.name} is too small to be a rendered document"
    assert count_pdf_pages(pdf) >= 1


def test_the_technical_report_fits_the_briefs_six_page_cap():
    """The brief's limit. If this fails the document is too long -- shorten it.

    Do not reach for the type sizes in `scripts/mdpdf/layout.py`: shrinking the font to slide
    under a page cap is the same dishonesty as tuning a constant until a gate goes green. For
    the record, the overrun this assertion first caught was not a property of this renderer:
    at eight pages here, Chrome laid out the same blocks at the same sizes and also gave eight,
    and the document only reached six at a 7 pt body, which is not a size anyone should be
    asked to read. It was cut instead.
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


@pytest.mark.parametrize("rel,cap", EXPECTED, ids=[p.stem for p, _ in EXPECTED])
def test_the_committed_pdf_is_what_the_markdown_renders_to_today(rel, cap):
    """A committed artifact that has drifted from its source reads as current, which is worse
    than not shipping it. `render` is a pure function of the parsed blocks plus the footer
    label, so a digest of the parsed markdown says everything about what the PDF should be --
    without depending on matplotlib's PDF bytes, which are not stable across versions.

    All six documents are covered, not only the two with page caps: a compliance matrix whose
    PDF no longer matches its markdown misleads a reviewer just as much, and this layer costs a
    parse rather than a render.
    """
    entry = manifest()["documents"].get(rel.as_posix())
    assert entry is not None, (
        f"{rel} is in the render list but has no entry in "
        f"{MANIFEST.relative_to(ROOT)}. {RERENDER}")
    assert structure_digest(ROOT / rel) == entry["markdown_sha256"], (
        f"{rel} has changed since {entry['pdf']} was rendered. {RERENDER}")
    committed = PDF_DIR / (rel.stem + ".pdf")
    assert file_digest(committed) == entry["pdf_sha256"], (
        f"{entry['pdf']} is not the file the manifest records. {RERENDER}")
    assert count_pdf_pages(committed) == entry["pages"]


@pytest.mark.parametrize("rel,cap", [(p, c) for p, c in EXPECTED if c is not None],
                         ids=[p.stem for p, c in EXPECTED if c is not None])
def test_a_re_render_is_byte_identical_on_the_recorded_matplotlib(rel, cap, tmp_path):
    """The renderer omits the PDF creation date so that an unchanged document re-renders
    byte-for-byte. That is a real property and worth asserting -- but only against the writer it
    was observed on. matplotlib's PDF output changes between versions and `pyproject.toml` pins
    `matplotlib>=3.7`, so on a cold clone with a different version this would fail saying the
    PDFs are stale when nothing is. The version-independent check above is the one that has to
    hold everywhere; this one adds the stronger guarantee where it is available.

    Only the two capped documents are re-rendered, to keep the cost to roughly a second: the
    digest check above already covers all six for the same class of staleness.
    """
    recorded = manifest()["matplotlib"]
    if matplotlib.__version__ != recorded:
        pytest.skip(f"PDFs were written on matplotlib {recorded}, this is "
                    f"{matplotlib.__version__}; byte-identity is not promised across versions. "
                    f"The manifest digest check covers staleness here.")
    from mdpdf import render
    fresh = tmp_path / (rel.stem + ".pdf")
    render(ROOT / rel, fresh, label=render_docs_pdf.label_for(rel.as_posix()))
    committed = PDF_DIR / (rel.stem + ".pdf")
    assert fresh.read_bytes() == committed.read_bytes(), (
        f"{committed.relative_to(ROOT)} is stale against {rel}. {RERENDER}")


def test_the_compliance_matrix_agrees_with_the_rendered_page_count():
    """D.7 asserted **Met** for 'Technical report, max 6 pages' while the report was eight
    pages, because nobody had rendered it. Whatever the status says, it has to agree with the
    PDF -- that is the only part of this a reviewer cannot check for themselves in a second."""
    matrix = ROOT / "docs" / "compliance_matrix.md"
    rows = [line for line in matrix.read_text().splitlines() if line.startswith("| D.7 ")]
    assert len(rows) == 1, (
        f"expected exactly one row starting '| D.7 ' in {matrix.relative_to(ROOT)}, found "
        f"{len(rows)}. The page-cap claim has to live somewhere a test can read it; if the row "
        f"was renumbered, update this test rather than dropping the check.")
    row = rows[0]
    pages = count_pdf_pages(PDF_DIR / "technical_report.pdf")
    # Match on the bold marker plus a word boundary, NOT the literal "**Met**". The literal
    # fails closed in the safe direction (a within-cap report whose row reads "**Met - 6
    # pages**" trips the second assert) but it lets the DANGEROUS direction through: an
    # over-cap report whose row reads "**Met - 8 pages**" sets claims_met False, so the first
    # assert never fires and the overclaim ships. "Not met" cannot match \*\*Met\b, so this
    # keeps the discrimination while refusing to be defeated by where the em-dash sits.
    claims_met = re.search(r"\*\*Met\b", row) is not None
    assert not (pages > 6 and claims_met), (
        f"compliance_matrix.md D.7 claims the 6-page cap is Met, but "
        f"submission/docs/technical_report.pdf is {pages} pages:\n  " + row.strip())
    assert not (pages <= 6 and not claims_met), (
        f"the report is within the cap at {pages} pages; D.7 should say Met:\n  " + row.strip())
    # Look in the STATUS cell, not the whole row. Both looser forms are vacuous here and a
    # mutation proved it: `str(pages) in row` is satisfied by the pt-size discussion, and
    # `f"{pages} pages" in row` is satisfied by the requirement column itself, which reads
    # "Technical report, max 6 pages" and therefore always contains "6 pages" when the count is
    # 6. Mutating the status to a wrong count passed both. The claim has to be checked where the
    # claim is made.
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    assert len(cells) >= 4, f"D.7 row does not have the expected 4 columns:\n  {row.strip()}"
    status = cells[3]
    assert f"{pages} pages" in status, (
        f"D.7's status cell should carry the measured page count ('{pages} pages') so a reviewer "
        f"can see what was counted rather than only that it passed. Status cell reads:\n  "
        + status)
