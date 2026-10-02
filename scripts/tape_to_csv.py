"""Turn the letter-keyed centimetre sheet into the CSV `bench/head_to_head.py` reads.

The operator measures against `data/own/dimensions.png`, where every quantity is one circled
letter, and writes centimetres into `data/own/measurements_cm.txt`. That is a far smaller target
to hit with a tape in hand than matching prose row names like `R1.W-topleft` to a physical wall,
and a correctly measured wall filed on the wrong row scores as an error exactly like a wrong one.

This does the mapping once, here, where it can be read and tested -- rather than asking a person
to do it twenty-six times from memory.

## It refuses rather than guesses

A unit slip is the failure this is most exposed to: 362 cm typed as 3.62, or a ceiling entered as
2.4 when every other line is in centimetres. Those produce a plausible CSV and a silently wrong
head-to-head. So each letter carries the range a real domestic measurement falls in, and anything
outside it stops the conversion and names the letter. The ranges are deliberately wide -- they
catch a factor-of-100 slip, not an unusual room.

Nothing is averaged away either: a second reading is kept as its own column, which is what the
reader expects and what lets a spread be seen rather than smoothed.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "own" / "measurements_cm.txt"
OUT = ROOT / "data" / "own" / "measurements.csv"

# letter -> (room, element, type, plausible cm range, note)
MAP: dict[str, tuple[str, str, str, tuple[float, float], str]] = {
    "a": ("R1", "R1.W-left",     "wall",           (80, 1500), ""),
    "b": ("R1", "R1.W-topleft",  "wall",           (30, 1500),
          "cupboard face, built-in, treated as wall"),
    "c": ("R1", "R1.W-notch",    "wall",           (10, 1500),
          "cupboard end, built-in, treated as wall"),
    "d": ("R1", "R1.W-topright", "wall",           (10, 1500), ""),
    "e": ("R1", "R1.W-right",    "wall",           (80, 1500), ""),
    "f": ("R1", "R1.W-bottom",   "wall",           (80, 1500),
          "corner to corner through the bathroom doorway"),
    "g": ("R1", "R1.O-bottom",   "opening_width",  (45, 180),  "bathroom doorway"),
    "h": ("R1", "R1.O-bottom",   "opening_height", (150, 260), "bathroom doorway"),
    "i": ("R1", "R1.O-right",    "opening_width",  (45, 250),  "main doorway"),
    "j": ("R1", "R1.O-right",    "opening_height", (150, 260), "main doorway"),
    "k": ("R1", "R1.X1",         "diagonal",       (100, 2000),
          "bottom-left to top-right"),
    "l": ("R1", "R1.X2",         "diagonal",       (100, 2000),
          "bottom-right to top-left at the cupboard front"),
    "m": ("R1", "R1.C1a",        "ceiling_part1",  (20, 120),  "floor to chair seat"),
    "n": ("R1", "R1.C1b",        "ceiling_part2",  (100, 300), "chair seat to ceiling"),
    "o": ("R1", "R1.C2a",        "ceiling_part1",  (20, 120),  "spot 2, floor to seat"),
    "p": ("R1", "R1.C2b",        "ceiling_part2",  (100, 300), "spot 2, seat to ceiling"),

    "q": ("R2", "R2.W1",         "wall",           (60, 1000), "left as you enter"),
    "r": ("R2", "R2.W2",         "wall",           (60, 1000), "ahead as you enter"),
    "s": ("R2", "R2.W3",         "wall",           (60, 1000), "right as you enter"),
    "t": ("R2", "R2.W4",         "wall",           (60, 1000),
          "door wall, corner to corner through the opening"),
    "u": ("R2", "R2.O1",         "opening_width",  (45, 180),  ""),
    "v": ("R2", "R2.O1",         "opening_height", (150, 260), ""),
    "w": ("R2", "R2.X1",         "diagonal",       (80, 1400), "top-left to bottom-right"),
    "x": ("R2", "R2.X2",         "diagonal",       (80, 1400), "top-right to bottom-left"),
    "y": ("R2", "R2.C1a",        "ceiling_part1",  (20, 120),  "floor to chair seat"),
    "z": ("R2", "R2.C1b",        "ceiling_part2",  (100, 300), "chair seat to ceiling"),
}

LINE = re.compile(r"^\s*([a-z])\s*=\s*([^#]*)")


def parse(text: str) -> tuple[dict[str, list[float]], list[str]]:
    values: dict[str, list[float]] = {}
    problems: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("#"):
            continue
        m = LINE.match(raw)
        if not m:
            continue
        letter, rhs = m.group(1), m.group(2).strip().rstrip(",")
        if letter not in MAP:
            problems.append(f"line {n}: '{letter}' is not one of a-z in the sheet")
            continue
        if not rhs:
            continue
        readings = []
        for part in rhs.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                readings.append(float(part))
            except ValueError:
                problems.append(f"line {n}: '{letter} = {part}' is not a number")
        if readings:
            values[letter] = readings
    return values, problems


def main() -> int:
    if not SRC.is_file():
        raise SystemExit(f"{SRC.relative_to(ROOT)} is missing")
    values, problems = parse(SRC.read_text())

    for letter, readings in sorted(values.items()):
        lo, hi = MAP[letter][3]
        for r in readings:
            if not (lo <= r <= hi):
                problems.append(
                    f"'{letter} = {r}' is outside {lo:g}-{hi:g} cm, the range a real "
                    f"{MAP[letter][1]} falls in. If that is genuinely the measurement, widen the "
                    f"range in scripts/tape_to_csv.py and say why; most often it is a unit slip "
                    f"(metres typed where the sheet asks for centimetres).")
        if len(readings) == 2 and abs(readings[0] - readings[1]) > 0.5:
            problems.append(
                f"'{letter}': two readings differ by {abs(readings[0] - readings[1]):.1f} cm "
                f"(> 0.5 cm). Take a third.")

    # Read-but-unused by head_to_head, so their absence is a decision rather than a gap.
    NOT_SCORED = {"k", "l", "w", "x", "h", "j", "v"}
    missing = [k for k in MAP if k not in values and k not in NOT_SCORED]
    missing_unscored = [k for k in MAP if k not in values and k in NOT_SCORED]
    if problems:
        print("REFUSING TO CONVERT:\n")
        for p in problems:
            print("  -", p)
        return 1

    rows = []
    for letter in MAP:
        if letter not in values:
            continue
        room, element, kind, _rng, note = MAP[letter]
        r = values[letter]
        rows.append({
            "room": room, "element": element, "type": kind,
            "reading1_m": f"{r[0] / 100.0:.4f}",
            "reading2_m": f"{r[1] / 100.0:.4f}" if len(r) > 1 else "",
            "note": (note + f" [{letter}]").strip(),
        })

    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["room", "element", "type",
                                           "reading1_m", "reading2_m", "note"])
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {OUT.relative_to(ROOT)}  ({len(rows)} of {len(MAP)} measurements)")
    by_room: dict[str, int] = {}
    for r in rows:
        by_room[r["room"]] = by_room.get(r["room"], 0) + 1
    for room, n in sorted(by_room.items()):
        print(f"  {room}: {n}")
    if missing:
        print(f"\n  MISSING AND SCORED ({len(missing)}): {', '.join(sorted(missing))}")
        print("  These are compared, so each one absent is a dimension the head-to-head simply "
              "cannot score. Nothing is invented for them. Fill them in and re-run.")
    if missing_unscored:
        print(f"\n  not measured, not scored: {', '.join(sorted(missing_unscored))}")
        print("  head_to_head reads these and does not compare them (door heights are not a "
              "magicplan dimension; diagonals test squareness rather than agreement). Their "
              "absence costs nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
