"""Flow blocks onto A4 pages and paint them with matplotlib.

Two stages, kept apart on purpose. `flow` turns blocks into a flat list of `Line`s, each one
carrying its own height and a closure that paints it at a given y. `paginate` then does nothing
but arithmetic on those heights. The page count is therefore a measured consequence of the
content, not something a renderer can be talked into — which is the whole point, since the
brief caps the technical report at six pages and a cap nobody checks is decoration.

The type sizes below are fixed by readability at print size and by matching the existing
one-page `report.pdf`. They are not knobs to turn when a document runs long: shrinking type to
slide under a page cap is the same dishonesty as tuning a constant to pass a gate. If a
document is over, the renderer says so and the document gets shorter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                        # noqa: E402
from matplotlib.lines import Line2D                                    # noqa: E402
from matplotlib.patches import Rectangle                               # noqa: E402

from . import blocks as B                                              # noqa: E402
from .text import FAMILY, Run, ascent, inline, substitute, width, wrap_runs   # noqa: E402

PAGE_W, PAGE_H = 595.276, 841.890            # A4 in PostScript points
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 48.0, 46.0, 44.0
CONTENT_W = PAGE_W - 2 * MARGIN_X

BODY = 9.0
LEADING = 1.34
MONO_RATIO = 0.93                            # DejaVu Mono runs wide; match the x-height by eye
H_SIZE = {1: 17.0, 2: 11.8, 3: 10.0, 4: 9.2, 5: 9.0, 6: 9.0}
TABLE = 7.9
TABLE_LEADING = 1.26
TABLE_PAD = 2.6
CODE = 7.6
CODE_LEADING = 1.24
FOOTER = 6.6

INK = "#111111"
MUTED = "#6b7280"
HEAD_RULE = "#9aa1ac"
GRID = "#b9bec7"
# Lifted from `th { background: #eef0f3 }` in cozmo-scan's scripts/report_pdf.py print CSS,
# and it appears nowhere else in this repo. Cosmetic, credited anyway -- see the provenance
# section in scripts/render_docs_pdf.py.
HEAD_FILL = "#eef0f3"
CODE_FILL = "#f4f5f7"
QUOTE_BAR = "#c3c8d0"

INDENT = 13.0                                # one list level
BULLET_GAP = 4.0


class Painter:
    """Draws in points measured from the top-left of the page."""

    def __init__(self, fig):
        self.fig = fig

    def text(self, x, y, s, *, size, bold=False, italic=False, mono=False, color=INK):
        self.fig.text(x / PAGE_W, 1.0 - y / PAGE_H, s,
                      fontsize=size, family=FAMILY["mono" if mono else "sans"],
                      fontweight="bold" if bold else "normal",
                      fontstyle="italic" if italic else "normal",
                      color=color, ha="left", va="baseline")

    def rule(self, x0, x1, y, *, color=GRID, lw=0.5):
        self.fig.add_artist(Line2D([x0 / PAGE_W, x1 / PAGE_W],
                                   [1.0 - y / PAGE_H, 1.0 - y / PAGE_H],
                                   color=color, linewidth=lw,
                                   transform=self.fig.transFigure))

    def box(self, x, y, w, h, *, fill=None, edge=None, lw=0.5):
        self.fig.add_artist(Rectangle((x / PAGE_W, 1.0 - (y + h) / PAGE_H),
                                      w / PAGE_W, h / PAGE_H,
                                      facecolor=fill or "none", edgecolor=edge or "none",
                                      linewidth=lw, transform=self.fig.transFigure, zorder=0))

    def runs(self, x, baseline, runs, size, color=INK):
        cx = x
        for run in runs:
            s = run.size or (size * MONO_RATIO if run.mono else size)
            self.text(cx, baseline, run.text, size=s, bold=run.bold, italic=run.italic,
                      mono=run.mono, color=run.color or color)
            cx += run.width(size, MONO_RATIO)


@dataclass
class Line:
    height: float
    draw: Callable[[Painter, float], None]
    space_before: float = 0.0
    keep_next: int = 0                       # lines that must land on this page too
    repeat: "Line | None" = None             # redrawn at the top of a page if split here


# ---- flow ---------------------------------------------------------------------------

def flow(doc: list[object]) -> list[Line]:
    lines: list[Line] = []
    for block in doc:
        if isinstance(block, B.Heading):
            lines += _heading(block)
        elif isinstance(block, B.Paragraph):
            lines += _paragraph(block.text)
        elif isinstance(block, B.ListBlock):
            lines += _list(block)
        elif isinstance(block, B.Table):
            lines += _table(block)
        elif isinstance(block, B.Code):
            lines += _code(block.lines, MARGIN_X)
        elif isinstance(block, B.Quote):
            lines += _quote(block)
        elif isinstance(block, B.Rule):
            lines.append(Line(1.0, lambda p, y: p.rule(MARGIN_X, PAGE_W - MARGIN_X, y,
                                                       color=HEAD_RULE, lw=0.6),
                              space_before=7.0))
    return lines


def _text_lines(runs: list[Run], x: float, avail: float, size: float, *,
                first_indent: float = 0.0, color: str = INK,
                leading: float = LEADING, space_before: float = 0.0,
                keep_next: int = 0, hang: list[Run] | None = None) -> list[Line]:
    wrapped = wrap_runs(runs, avail, size, MONO_RATIO, first_indent)
    asc, step = ascent(size), size * leading
    out: list[Line] = []
    for n, line_runs in enumerate(wrapped):
        def paint(p: Painter, y: float, line_runs=line_runs, n=n):
            if n == 0 and hang:                      # the list marker, in the reserved column
                p.runs(x, y + asc, hang, size, color)
            p.runs(x + first_indent, y + asc, line_runs, size, color)

        out.append(Line(step, paint, space_before=space_before if n == 0 else 0.0,
                        keep_next=keep_next if n == 0 else 0))
    return out


def _heading(h: B.Heading) -> list[Line]:
    size = H_SIZE[h.level]
    gap = {1: 0.0, 2: 13.0, 3: 9.0}.get(h.level, 7.0)
    runs = [Run(substitute(h.text), bold=h.level > 1, size=size)]
    out = _text_lines(runs, MARGIN_X, CONTENT_W, size, leading=1.18,
                      space_before=gap, keep_next=3)
    if h.level <= 2:
        pad = 4.0 if h.level == 1 else 2.6
        out.append(Line(pad + 2.0,
                        lambda p, y: p.rule(MARGIN_X, PAGE_W - MARGIN_X, y + pad,
                                            color=HEAD_RULE, lw=0.7 if h.level == 1 else 0.5)))
    else:
        out.append(Line(1.6, lambda p, y: None))
    return out


def _paragraph(text: str, x: float = MARGIN_X, avail: float = CONTENT_W) -> list[Line]:
    return _text_lines(inline(text), x, avail, BODY, space_before=4.6)


def _list(block: B.ListBlock) -> list[Line]:
    out: list[Line] = []
    for n, item in enumerate(block.items):
        x = MARGIN_X + item.depth * INDENT
        marker = [Run(substitute(item.marker), bold=item.marker != "•")]
        reserve = max(width(item.marker, BODY, bold=True) + BULLET_GAP, 11.0)
        if item.text:
            out += _text_lines(inline(item.text), x, CONTENT_W - item.depth * INDENT - reserve,
                               BODY, first_indent=reserve, hang=marker,
                               space_before=4.6 if n == 0 else 2.4)
        else:
            out.append(Line(BODY * LEADING,
                            lambda p, y, x=x, marker=marker: p.runs(x, y + ascent(BODY), marker,
                                                                    BODY),
                            space_before=4.6 if n == 0 else 2.4))
        if item.code:
            out += _code(item.code, x + reserve)
    return out


def _code(code_lines: list[str], x: float) -> list[Line]:
    step = CODE * CODE_LEADING
    asc = ascent(CODE, "mono")
    avail = PAGE_W - MARGIN_X - x - 8.0
    out: list[Line] = [Line(3.2, lambda p, y, x=x: p.box(x - 4, y - 1.0,
                                                         PAGE_W - MARGIN_X - x + 4, 4.2,
                                                         fill=CODE_FILL), space_before=4.4)]
    for raw in code_lines or [""]:
        for piece in _fit_mono(substitute(raw.rstrip()), avail):
            def paint(p: Painter, y: float, piece=piece, x=x):
                p.box(x - 4, y - 1.0, PAGE_W - MARGIN_X - x + 4, step, fill=CODE_FILL)
                p.text(x, y + asc, piece, size=CODE, mono=True)
            out.append(Line(step, paint))
    out.append(Line(4.2, lambda p, y, x=x: p.box(x - 4, y - 1.0,
                                                 PAGE_W - MARGIN_X - x + 4, 4.2, fill=CODE_FILL)))
    return out


def _fit_mono(text: str, avail: float) -> list[str]:
    """Code never reflows on words; it breaks at the last column that fits."""
    if width(text, CODE, "mono") <= avail or not text:
        return [text]
    out, cur = [], ""
    for ch in text:
        if width(cur + ch, CODE, "mono") > avail and cur:
            out.append(cur)
            cur = "    " + ch if ch != " " else "    "
        else:
            cur += ch
    return out + [cur]


def _quote(block: B.Quote) -> list[Line]:
    x = MARGIN_X + 10.0
    body = _text_lines(inline(" ".join(l.strip() for l in block.lines if l.strip())),
                       x, CONTENT_W - 10.0, BODY, color="#333333", space_before=5.0)
    bar = [Line(l.height, _with_bar(l.draw, x), l.space_before, l.keep_next) for l in body]
    return bar


def _with_bar(draw, x):
    def painted(p: Painter, y: float):
        p.box(x - 7.0, y - 1.0, 1.8, BODY * LEADING, fill=QUOTE_BAR)
        draw(p, y)
    return painted


# ---- tables -------------------------------------------------------------------------

def _column_widths(table: B.Table) -> list[float]:
    cols = table.columns
    natural = [0.0] * cols
    minimum = [0.0] * cols
    for row, bold in [(table.header, True)] + [(r, False) for r in table.rows]:
        for c in range(cols):
            runs = inline(row[c], bold=bold) if c < len(row) else []
            natural[c] = max(natural[c], sum(r.width(TABLE, MONO_RATIO) for r in runs))
            longest = max([max((w.width(TABLE, MONO_RATIO)
                                for w in [r.with_text(t) for t in r.text.split()]), default=0.0)
                           for r in runs], default=0.0)
            minimum[c] = max(minimum[c], longest)
    pad = 2 * TABLE_PAD
    natural = [w + pad for w in natural]
    minimum = [min(w + pad, CONTENT_W / cols * 2) for w in minimum]

    total = sum(natural)
    if total <= CONTENT_W:                                 # spread the slack, keep the ratios
        extra = CONTENT_W - total
        return [w + extra * (w / total if total else 1 / cols) for w in natural]

    # Over-wide: take the overflow from the columns that have room above their longest word.
    widths = list(natural)
    for _ in range(cols):
        over = sum(widths) - CONTENT_W
        if over <= 0.1:
            break
        slack = [max(0.0, widths[c] - minimum[c]) for c in range(cols)]
        if sum(slack) <= 0.1:
            break
        take = min(over / sum(slack), 1.0)
        widths = [widths[c] - slack[c] * take for c in range(cols)]
    if sum(widths) > CONTENT_W:                            # every column is at its minimum
        scale = CONTENT_W / sum(widths)
        widths = [w * scale for w in widths]
    return widths


def _cell_lines(row: list[str], widths: list[float], bold: bool) -> list[list[list[Run]]]:
    out = []
    for c, w in enumerate(widths):
        text = row[c] if c < len(row) else ""
        runs = inline(text, bold=bold)
        out.append(wrap_runs(runs, w - 2 * TABLE_PAD, TABLE, MONO_RATIO) if runs else [[]])
    return out


def _row_line(row: list[str], widths: list[float], aligns: list[str], *, head: bool,
              space_before: float = 0.0, keep_next: int = 0) -> Line:
    cells = _cell_lines(row, widths, head)
    step = TABLE * TABLE_LEADING
    height = max(len(c) for c in cells) * step + 2 * TABLE_PAD
    asc = ascent(TABLE)

    def paint(p: Painter, y: float):
        x = MARGIN_X
        if head:
            p.box(MARGIN_X, y, sum(widths), height, fill=HEAD_FILL)
        for c, w in enumerate(widths):
            p.box(x, y, w, height, edge=GRID, lw=0.45)
            for n, line_runs in enumerate(cells[c]):
                used = sum(r.width(TABLE, MONO_RATIO) for r in line_runs)
                if aligns[c] == "right":
                    off = w - TABLE_PAD - used
                elif aligns[c] == "center":
                    off = (w - used) / 2
                else:
                    off = TABLE_PAD
                p.runs(x + off, y + TABLE_PAD + n * step + asc, line_runs, TABLE)
            x += w

    return Line(height, paint, space_before=space_before, keep_next=keep_next)


def _table(table: B.Table) -> list[Line]:
    widths = _column_widths(table)
    aligns = (table.aligns + ["left"] * table.columns)[:table.columns]
    blank_header = not any(h.strip() for h in table.header)
    out: list[Line] = []
    header = None
    if not blank_header:
        header = _row_line(table.header, widths, aligns, head=True, space_before=5.0,
                           keep_next=1)
        out.append(header)
    for n, row in enumerate(table.rows):
        out.append(_row_line(row, widths, aligns, head=False,
                             space_before=5.0 if blank_header and n == 0 else 0.0))
        if header is not None:
            out[-1].repeat = _row_line(table.header, widths, aligns, head=True)
    out.append(Line(2.0, lambda p, y: None))
    return out


# ---- pagination ---------------------------------------------------------------------

@dataclass
class Page:
    placed: list[tuple[Line, float]] = field(default_factory=list)


def paginate(lines: list[Line]) -> list[Page]:
    bottom = PAGE_H - MARGIN_BOTTOM
    pages: list[Page] = []
    page, y = Page(), MARGIN_TOP

    def need(i: int) -> float:
        total = lines[i].height
        for k in range(1, lines[i].keep_next + 1):
            if i + k >= len(lines):
                break
            total += lines[i + k].space_before + lines[i + k].height
        return total

    i = 0
    while i < len(lines):
        line = lines[i]
        gap = line.space_before if page.placed else 0.0
        if page.placed and y + gap + need(i) > bottom:
            pages.append(page)
            page, y, gap = Page(), MARGIN_TOP, 0.0
            if line.repeat is not None:
                page.placed.append((line.repeat, y))
                y += line.repeat.height
        y += gap
        page.placed.append((line, y))
        y += line.height
        i += 1
    if page.placed:
        pages.append(page)
    return pages or [Page()]


# ---- paint --------------------------------------------------------------------------

def paint(pages: list[Page], out_pdf, label: str) -> int:
    """Write every page and return how many there were."""
    from matplotlib.backends.backend_pdf import PdfPages

    # CreationDate omitted so a re-render of unchanged markdown is a byte-identical file:
    # these PDFs are committed, and a timestamp would make every build a diff.
    with PdfPages(out_pdf, metadata={"Creator": "scanplan/render_docs_pdf",
                                     "Producer": "matplotlib",
                                     "CreationDate": None}) as pdf:
        for n, page in enumerate(pages, start=1):
            fig = plt.figure(figsize=(PAGE_W / 72.0, PAGE_H / 72.0))
            p = Painter(fig)
            for line, y in page.placed:
                line.draw(p, y)
            p.text(MARGIN_X, PAGE_H - MARGIN_BOTTOM + 22.0, label, size=FOOTER, color=MUTED)
            right = f"page {n} of {len(pages)}"
            p.text(PAGE_W - MARGIN_X - width(right, FOOTER),
                   PAGE_H - MARGIN_BOTTOM + 22.0, right, size=FOOTER, color=MUTED)
            pdf.savefig(fig)
            plt.close(fig)
    return len(pages)
