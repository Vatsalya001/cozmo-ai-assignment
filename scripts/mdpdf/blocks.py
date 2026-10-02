"""Markdown text to a flat list of blocks. The subset these documents actually use.

Scope was chosen by reading the six documents rather than by guessing: ATX headings, fenced
code, GitHub pipe tables (including the header-less `| | |` form in `capture_protocol.md`),
bullet and ordered lists with one level of nesting, blockquotes, horizontal rules, paragraphs.
Anything outside that is passed through as a paragraph, which degrades to "the words are still
there" rather than to a crash.

One ordering subtlety: `---` is a horizontal rule on its own and a table separator directly
under a pipe row, so tables are recognised before rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^\s*```+\s*(\S*)\s*$")
RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
QUOTE = re.compile(r"^\s*>\s?(.*)$")
SEPARATOR = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


@dataclass
class Heading:
    level: int
    text: str


@dataclass
class Paragraph:
    text: str


@dataclass
class Code:
    lines: list[str]
    language: str = ""


@dataclass
class Rule:
    pass


@dataclass
class Quote:
    lines: list[str]


@dataclass
class Item:
    marker: str
    text: str
    depth: int
    code: list[str] = field(default_factory=list)   # a fenced block opened on the item's line


@dataclass
class ListBlock:
    items: list[Item] = field(default_factory=list)


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    aligns: list[str]

    @property
    def columns(self) -> int:
        return max([len(self.header)] + [len(r) for r in self.rows])


_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> list[str]:
    """Split a pipe row, honouring `\\|` inside a cell (`median \\|error\\|` in declined_changes)."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE.split(body)]


def _is_row(line: str) -> bool:
    return "|" in line and not FENCE.match(line)


def _alignments(sep: str, n: int) -> list[str]:
    out = []
    for cell in _cells(sep):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("center" if left and right else "right" if right else "left")
    return (out + ["left"] * n)[:n]


def parse(markdown: str) -> list[object]:
    lines = markdown.replace("\t", "    ").splitlines()
    blocks: list[object] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        fence = FENCE.match(line)
        if fence:
            body, i = [], i + 1
            while i < n and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            blocks.append(Code(body, fence.group(1)))
            i += 1
            continue

        head = HEADING.match(line)
        if head:
            blocks.append(Heading(len(head.group(1)), head.group(2).strip().rstrip("#").strip()))
            i += 1
            continue

        if _is_row(line) and i + 1 < n and SEPARATOR.match(lines[i + 1]) and "|" in lines[i + 1]:
            header, separator = _cells(line), lines[i + 1]
            rows, i = [], i + 2
            while i < n and _is_row(lines[i]) and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            width = max([len(header)] + [len(r) for r in rows])
            blocks.append(Table(header, rows, _alignments(separator, width)))
            continue

        if RULE.match(line):
            blocks.append(Rule())
            i += 1
            continue

        quote = QUOTE.match(line)
        if quote:
            body = []
            while i < n and (m := QUOTE.match(lines[i])):
                body.append(m.group(1))
                i += 1
            blocks.append(Quote(body))
            continue

        if BULLET.match(line) or ORDERED.match(line):
            items, i = _list_items(lines, i, n)
            blocks.append(ListBlock(items))
            continue

        # Always consume this line first: a prose line can contain a '|' without being a table
        # (`docs/declined_changes.md` has `median \|error\|`), and leaving it for the loop to
        # re-examine is a hang, which is exactly what happened.
        body, i = [lines[i].strip()], i + 1
        while i < n and lines[i].strip() and not _starts_block(lines[i]):
            body.append(lines[i].strip())
            i += 1
        blocks.append(Paragraph(" ".join(body)))

    return blocks


def _starts_block(line: str) -> bool:
    return bool(HEADING.match(line) or FENCE.match(line) or RULE.match(line)
                or BULLET.match(line) or ORDERED.match(line) or QUOTE.match(line)
                or _is_row(line))


def _list_items(lines: list[str], i: int, n: int) -> tuple[list[Item], int]:
    """Consume one list. Continuation lines fold into the item; indentation sets depth."""
    items: list[Item] = []
    while i < n and lines[i].strip():
        bullet, ordered = BULLET.match(lines[i]), ORDERED.match(lines[i])
        if bullet:
            indent, marker, text = bullet.group(1), "•", bullet.group(2)
        elif ordered:
            indent, marker, text = ordered.group(1), f"{ordered.group(2)}.", ordered.group(3)
        elif items and not _starts_block(lines[i]):
            items[-1].text += " " + lines[i].strip()
            i += 1
            continue
        else:
            break
        item = Item(marker, text.strip(), min(len(indent) // 2, 2))
        items.append(item)
        i += 1
        if FENCE.match(item.text):            # `3. ```bash` in docs/walk_in.md
            item.text = ""
            while i < n and not FENCE.match(lines[i]):
                item.code.append(lines[i].strip())
                i += 1
            i += 1
    return items, i
