"""Font metrics, inline markdown, and line breaking — measured in PostScript points.

Why measure at all: wrapping text by counting characters is wrong for a proportional font, and
wrong wrapping is what makes a generated PDF look generated. The widths here come from the
`hmtx` table of the same TTF matplotlib will draw with, so a line this module says fits is a
line that fits. fontTools is already installed — it is a hard dependency of matplotlib — so
this costs no new package.

The other job is glyph honesty. DejaVu has no U+2705 (white heavy check mark) or U+274C, and
`docs/walk_in.md` uses both in its gate table. matplotlib would draw a hollow box and the
reviewer would read "broken tool", so characters absent from the font are mapped to the nearest
glyph that exists and anything still unmappable is reported by name rather than silently
squared off.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import matplotlib
from fontTools.ttLib import TTFont

TTF_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"

FAMILY = {"sans": "DejaVu Sans", "mono": "DejaVu Sans Mono"}
_FILES = {
    ("sans", False, False): "DejaVuSans.ttf",
    ("sans", True, False): "DejaVuSans-Bold.ttf",
    ("sans", False, True): "DejaVuSans-Oblique.ttf",
    ("sans", True, True): "DejaVuSans-BoldOblique.ttf",
    ("mono", False, False): "DejaVuSansMono.ttf",
    ("mono", True, False): "DejaVuSansMono-Bold.ttf",
    ("mono", False, True): "DejaVuSansMono-Oblique.ttf",
    ("mono", True, True): "DejaVuSansMono-BoldOblique.ttf",
}

# Nearest glyph that DejaVu actually ships. Each entry is a deliberate downgrade, not a guess:
# the check/cross pair keeps the gate tables readable in monochrome print, which the emoji
# originals would not have done anyway.
SUBSTITUTIONS = {
    "✅": "✔",      # white heavy check mark -> heavy check mark
    "❌": "✘",      # cross mark             -> heavy ballot x
    "⚪": "○",      # white circle (emoji)   -> white circle (geometric; in mono too)
    "️": "",            # variation selector-16: an emoji request we cannot honour
    " ": " ",
}

unmapped: set[str] = set()                 # reported by the CLI; see render_docs_pdf.py


@lru_cache(maxsize=None)
def _font(family: str, bold: bool, italic: bool) -> tuple[dict, int, float, float]:
    """(advance width by codepoint, units per em, ascent, descent) for one face."""
    ttf = TTFont(TTF_DIR / _FILES[(family, bold, italic)])
    upem = ttf["head"].unitsPerEm
    widths = ttf["hmtx"].metrics
    cmap = ttf.getBestCmap()
    by_cp = {cp: widths[name][0] for cp, name in cmap.items() if name in widths}
    hhea = ttf["hhea"]
    return by_cp, upem, hhea.ascent / upem, -hhea.descent / upem


def substitute(text: str) -> str:
    """Replace characters DejaVu cannot draw. Records anything left over."""
    out = []
    cp_map = _font("sans", False, False)[0]
    for ch in text:
        if ch in SUBSTITUTIONS:
            out.append(SUBSTITUTIONS[ch])
        elif ord(ch) < 32 or ord(ch) in cp_map:
            out.append(ch)
        else:
            unmapped.add(ch)
            out.append("?")
    return "".join(out)


def width(text: str, size: float, family: str = "sans", bold: bool = False,
          italic: bool = False) -> float:
    cp_map, upem, _, _ = _font(family, bold, italic)
    fallback = cp_map.get(ord(" "), upem // 2)
    return sum(cp_map.get(ord(c), fallback) for c in text) * size / upem


def ascent(size: float, family: str = "sans") -> float:
    return _font(family, False, False)[2] * size


# ---- inline markdown ----------------------------------------------------------------

@dataclass(frozen=True)
class Run:
    """One stretch of text that shares a single face and size."""
    text: str
    bold: bool = False
    italic: bool = False
    mono: bool = False
    size: float | None = None               # None -> the caller's body size
    color: str | None = None

    def with_text(self, text: str) -> "Run":
        return Run(text, self.bold, self.italic, self.mono, self.size, self.color)

    def width(self, body_size: float, mono_ratio: float) -> float:
        size = self.size or (body_size * mono_ratio if self.mono else body_size)
        return width(self.text, size, "mono" if self.mono else "sans", self.bold, self.italic)


_INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>(?:[^*]|\*(?!\*))+)\*\*"
    r"|(?<![\w*])\*(?P<em>[^*\s][^*]*?)\*(?![\w*])"
    r"|\[(?P<link>[^\]]+)\]\((?P<href>[^)]*)\)"
)
LINK_COLOR = "#1a56db"
CODE_COLOR = "#8a2a2a"


def inline(text: str, *, bold: bool = False, link_color: str = LINK_COLOR) -> list[Run]:
    """Markdown emphasis, code spans and links, as a flat list of runs.

    Deliberately a subset: nesting deeper than bold-around-code does not occur in these
    documents, and a general inline parser would be more code than the job needs.
    """
    runs: list[Run] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            runs.append(Run(substitute(text[pos:m.start()]), bold=bold))
        if m.group("code") is not None:
            runs.append(Run(substitute(m.group("code")), bold=bold, mono=True, color=CODE_COLOR))
        elif m.group("bold") is not None:
            runs.extend(inline(m.group("bold"), bold=True, link_color=link_color))
        elif m.group("em") is not None:
            runs.append(Run(substitute(m.group("em")), bold=bold, italic=True))
        else:
            runs.append(Run(substitute(m.group("link")), bold=bold, color=link_color))
        pos = m.end()
    if pos < len(text):
        runs.append(Run(substitute(text[pos:]), bold=bold))
    return [r for r in runs if r.text]


# ---- breaking -----------------------------------------------------------------------

_SPLIT = re.compile(r"(\s+)")


def wrap_runs(runs: list[Run], max_width: float, body_size: float,
              mono_ratio: float, first_indent: float = 0.0) -> list[list[Run]]:
    """Greedy break of a run sequence into lines no wider than `max_width`.

    `first_indent` is the room a list marker takes on the first line; continuation lines keep
    the same left edge, so the limit is the same on every line and only the start differs.
    """
    lines: list[list[Run]] = []
    cur: list[Run] = []
    used = 0.0
    limit = max_width

    for run in runs:
        for piece in (p for p in _SPLIT.split(run.text) if p):
            w = run.with_text(piece).width(body_size, mono_ratio)
            if piece.isspace():
                if cur:                       # never start a line with a space
                    cur.append(run.with_text(" "))
                    used += w
                continue
            if used + w > limit and cur:
                while cur and cur[-1].text.isspace():
                    cur.pop()
                lines.append(cur)
                cur, used = [], 0.0
            if w > limit and not cur:         # one unbreakable token wider than the column
                chunks = _hard_split(run, piece, limit, body_size, mono_ratio)
                lines.extend([c] for c in chunks[:-1])
                cur = [chunks[-1]]
                used = chunks[-1].width(body_size, mono_ratio)
                continue
            cur.append(run.with_text(piece))
            used += w
    while cur and cur[-1].text.isspace():
        cur.pop()
    if cur or not lines:
        lines.append(cur)
    return lines


def _hard_split(run: Run, token: str, limit: float, body_size: float,
                mono_ratio: float) -> list[Run]:
    """Break a single over-long token (a path, a URL) at whatever character fits."""
    out, cur = [], ""
    for ch in token:
        if run.with_text(cur + ch).width(body_size, mono_ratio) > limit and cur:
            out.append(run.with_text(cur))
            cur = ch
        else:
            cur += ch
    out.append(run.with_text(cur))
    return out
