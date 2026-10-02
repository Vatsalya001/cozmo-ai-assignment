"""Draw the capture plan for `data/own` onto the magicplan layout.

The photo tier needs the operator to stand in specific places and aim in specific directions,
and prose instructions for that are genuinely hard to follow while holding a phone in a room.
So the positions are drawn on the plan the operator already has.

Geometry comes from `data/own/magicplan/My New Project - Ground Floor.dxf` -- the DXF is the
authority, not the report PDF, and not anything typed in by hand here.

## No dimensions appear on this drawing, deliberately

`data/own/measurements_to_fill.csv` says MEASURE BLIND: the tape readings are the ground truth
that scores both magicplan and this pipeline, so an operator who has seen magicplan's lengths
cannot produce an independent reading, and the head-to-head would then be scoring magicplan
against a copy of itself. The drawing therefore carries wall IDs, door positions and camera
stations, and **no lengths, no areas and no scale bar** -- everything needed to identify a wall,
nothing that pre-empts measuring it.

Wall IDs match the `element` column of `measurements_to_fill.csv` exactly, so a reader can go
from a line on the drawing to a row in the sheet without interpretation.
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DXF = ROOT / "data" / "own" / "magicplan" / "My New Project - Ground Floor.dxf"
OUT_PNG = ROOT / "data" / "own" / "capture_plan.png"
OUT_PDF = ROOT / "data" / "own" / "capture_plan.pdf"

WALL = "#2b3a4a"
OPENING = "#c0392b"
CAM = "#1f6f3f"
TAPE = "#7a5c00"


def dxf_polylines(path: Path) -> list[list[tuple[float, float]]]:
    """Closed LWPOLYLINE vertex lists, in file order.

    A minimal reader rather than a DXF library: this file is 78 polylines on one layer, and
    adding a dependency to read three of them would be the wrong trade.
    """
    raw = path.read_text(errors="replace").splitlines()
    pairs = [(raw[i].strip(), raw[i + 1].strip()) for i in range(0, len(raw) - 1, 2)]
    out, cur, pts = [], None, []
    for code, val in pairs:
        if code == "0":
            if cur == "LWPOLYLINE" and len(pts) >= 3:
                out.append(pts)
            cur, pts = val, []
        elif cur == "LWPOLYLINE":
            if code == "10":
                pts.append([float(val), None])
            elif code == "20" and pts and pts[-1][1] is None:
                pts[-1][1] = float(val)
    if cur == "LWPOLYLINE" and len(pts) >= 3:
        out.append(pts)
    return [[(round(a, 3), round(b, 3)) for a, b in p if b is not None] for p in out]


# --- The two rooms, read off the DXF polylines -------------------------------------------
# Inner wall faces. Each entry is (wall_id, (x0, y0), (x1, y1)). `None` as the id means the
# segment is a doorway rather than a wall, and is drawn as a gap.
#
# These were derived from the DXF polyline vertices: the bedroom wall band gives inner faces at
# x=-2.27 and y=-2.38 and the stepped top at y=1.24 / y=1.73, the separate right-hand wall
# polyline gives x=1.16, and the gaps between solid runs are where the three INSERT door
# symbols sit (bedroom bottom at x~0.08, bedroom top-right at x~0.71, bathroom right at y~0.07).

BEDROOM = [
    ("W-left",     (-2.27, -2.38), (-2.27, 1.24)),
    ("W-topleft",  (-2.27, 1.24),  (-0.49, 1.24)),
    ("W-notch",    (-0.49, 1.24),  (-0.49, 1.73)),
    ("W-topright", (-0.49, 1.73),  (0.26, 1.73)),
    (None,         (0.26, 1.73),   (1.16, 1.73)),      # O-right
    ("W-right",    (1.16, 1.73),   (1.16, -2.38)),
    ("W-bottom",   (1.16, -2.38),  (0.46, -2.38)),
    (None,         (0.46, -2.38),  (-0.31, -2.38)),    # O-bottom
    ("W-bottom",   (-0.31, -2.38), (-2.27, -2.38)),
]

BATHROOM = [
    ("W2", (2.32, 0.46),   (2.32, -1.11)),
    ("W3", (2.32, -1.11),  (4.09, -1.11)),
    ("W4", (4.09, -1.11),  (4.09, -0.32)),
    (None, (4.09, -0.32),  (4.09, 0.46)),              # O1
    ("W1", (4.09, 0.46),   (2.32, 0.46)),
]

# --- Camera stations ---------------------------------------------------------------------
# A station is ONE place to stand, carrying several numbered shots. Modelling it this way
# instead of one marker per shot matters: four of the bedroom shots are taken without moving,
# and a marker per shot drew four dots on one pixel with their labels overprinted.
# Aim is degrees anticlockwise from +x (plan east). Shot numbers sit at the arrow tips.
# Corrected after the operator identified the rooms: the WIDE opening is the main way in, the
# opening in the long wall leads to the bathroom, and the "notch" is a built-in cupboard --
# W-topleft is its front (the doors) and W-notch is its end. Both are treated as wall, which is
# what magicplan did and what a floor plan is for; the convention is recorded rather than assumed.
BEDROOM_STATIONS = [
    ("A", (0.71, 1.60),  "in the MAIN doorway", [(1, -90), (2, -125), (3, -158), (4, -52)]),
    ("B", (-1.38, -0.30), "mid-room, facing the cupboard front", [(5, 90)]),
    ("C", (0.45, 0.80),  "right of the cupboard, looking along it", [(6, 180)]),
    ("D", (0.08, -1.55), "inside, square at the bathroom door", [(7, -90)]),
    ("E", (0.71, 0.05),  "inside, square at the main doorway", [(8, 90)]),
]

BATHROOM_STATIONS = [
    ("A", (3.97, 0.07),  "in the doorway", [(1, 180), (2, 147), (3, 213)]),
    ("B", (2.52, -0.92), "far corner, diagonally opposite", [(4, 30), (5, 78)]),
    ("C", (3.28, -0.16), "inside, facing the doorway", [(6, 9)]),
]


def draw_room(ax, segments, stations, title, label_offsets):
    for wid, a, b in segments:
        colour, width = (OPENING, 6) if wid is None else (WALL, 6)
        ax.plot([a[0], b[0]], [a[1], b[1]], color=colour, lw=width,
                solid_capstyle="butt", zorder=3 if wid is None else 2)

    seen = set()
    for wid, a, b in segments:
        if wid is None or wid in seen:
            continue
        seen.add(wid)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dy = label_offsets.get(wid, (0.0, 0.0))
        ax.annotate(wid, (mx + dx, my + dy), color=WALL, fontsize=9, weight="bold",
                    ha="center", va="center", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=WALL, lw=0.8))

    for letter, (x, y), _note, shots in stations:
        for num, deg in shots:
            rad = math.radians(deg)
            r = 0.78
            ax.annotate("", xy=(x + r * math.cos(rad), y + r * math.sin(rad)), xytext=(x, y),
                        arrowprops=dict(arrowstyle="-|>", color=CAM, lw=1.9,
                                        mutation_scale=15, shrinkA=9, shrinkB=0), zorder=5)
            tx, ty = x + (r + 0.21) * math.cos(rad), y + (r + 0.21) * math.sin(rad)
            ax.annotate(str(num), (tx, ty), color="white", fontsize=8, weight="bold",
                        ha="center", va="center", zorder=8,
                        bbox=dict(boxstyle="circle,pad=0.22", fc=CAM, ec="white", lw=1.1))
        ax.plot([x], [y], marker="o", ms=19, mfc="white", mec=CAM, mew=2.4, zorder=7)
        ax.annotate(letter, (x, y), color=CAM, fontsize=11, weight="bold",
                    ha="center", va="center", zorder=9)

    ax.set_title(title, fontsize=12, weight="bold", color=WALL, pad=14)
    ax.set_aspect("equal")
    ax.margins(0.18)
    ax.axis("off")


def main() -> int:
    if not DXF.is_file():
        raise SystemExit(f"{DXF} is missing; the drawing is derived from it, not hand-typed")
    dxf_polylines(DXF)  # parsed as a check that the file still looks the way this assumes

    fig, axes = plt.subplots(1, 2, figsize=(14.0, 9.2),
                             gridspec_kw={"width_ratios": [1.0, 0.82]})

    draw_room(axes[0], BEDROOM, BEDROOM_STATIONS, "BEDROOM  (sheet rows R1.*)",
              # W-notch sits in the cut-away void beside the step it names: its midpoint label
              # and W-topright's landed on the same point and the notch label disappeared under
              # the other one. W-bottom is shifted onto the long left run rather than the short
              # right stub, which is the segment the `seen` set happens to reach first.
              {"W-left": (0.34, 0.0), "W-topleft": (0.0, -0.32), "W-notch": (0.46, 0.22),
               "W-topright": (-0.02, -0.40), "W-right": (-0.34, 0.0),
               "W-bottom": (-2.10, 0.30)})
    draw_room(axes[1], BATHROOM, BATHROOM_STATIONS, "BATHROOM  (sheet rows R2.*)",
              {"W1": (0.0, -0.24), "W2": (0.28, 0.0), "W3": (0.0, 0.24), "W4": (-0.26, 0.0)})

    # Openings get their sheet ids too, so a reader can find them in the CSV.
    axes[0].annotate("O-bottom\n\u2192 to BATHROOM", (0.08, -2.58), color=OPENING, fontsize=8.5,
                     weight="bold", ha="center", va="top")
    axes[0].annotate("O-right  \u2014  MAIN DOORWAY (start here)", (0.71, 1.95), color=OPENING,
                     fontsize=9, weight="bold", ha="center", va="bottom")
    axes[0].annotate("BUILT-IN\nCUPBOARD\n(counts as wall)",
                     (-1.38, 1.49), color=WALL, fontsize=8, style="italic", ha="center",
                     va="center", zorder=6,
                     bbox=dict(boxstyle="round,pad=0.3", fc="#eef1f4", ec=WALL, lw=0.8,
                               alpha=0.95))
    axes[1].annotate("O1", (4.16, 0.52), color=OPENING, fontsize=8.5, weight="bold",
                     ha="left", va="bottom")

    legend = (
        "dark line = wall to measure        red line = doorway (a gap, not a wall)\n"
        "green dot = where to stand         green arrow = where to point the camera\n"
        "Wall ids match the element column of measurements_to_fill.csv exactly.\n"
        "Grey block = the built-in cupboard. It is fixed, so it counts as wall.\n"
        "No lengths, areas or scale bar appear here: the tape readings are the ground truth\n"
        "that scores magicplan, so seeing its numbers first would make them worthless."
    )
    fig.text(0.5, 0.175, legend, ha="center", va="top", fontsize=8.6, color=WALL,
             family="monospace",
             bbox=dict(boxstyle="round,pad=0.6", fc="#f6f7f9", ec=WALL, lw=0.8))
    fig.suptitle("Capture plan — where to stand, where to aim, which wall is which",
                 fontsize=13, weight="bold", color=WALL, y=0.97)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.91, bottom=0.235, wspace=0.05)

    fig.savefig(OUT_PNG, dpi=170)
    fig.savefig(OUT_PDF)
    plt.close(fig)
    print(f"wrote {OUT_PNG.relative_to(ROOT)}")
    print(f"wrote {OUT_PDF.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# --- The dimension sheet -------------------------------------------------------------------
# A second drawing, kept separate from the capture plan so neither is cluttered: this one marks
# every quantity to be taped with a single letter, so the operator writes "a = 362" instead of
# matching prose row names to physical walls. a-z covers it exactly.
DIM_BEDROOM = [
    ("a", (-2.27, -2.38), (-2.27, 1.24)),      # W-left
    ("b", (-2.27, 1.24),  (-0.49, 1.24)),      # W-topleft  = cupboard front
    ("c", (-0.49, 1.24),  (-0.49, 1.73)),      # W-notch    = cupboard end
    ("d", (-0.49, 1.73),  (0.26, 1.73)),       # W-topright
    ("e", (1.16, 1.73),   (1.16, -2.38)),      # W-right
    ("f", (-2.27, -2.38), (1.16, -2.38)),      # W-bottom, corner to corner THROUGH the door
]
DIM_BEDROOM_OPEN = [("g", (-0.31, -2.38), (0.46, -2.38)),   # bathroom door width
                    ("i", (0.26, 1.73),   (1.16, 1.73))]    # main doorway width
DIM_BEDROOM_DIAG: list = []   # diagonals dropped: head_to_head reads and ignores them

DIM_BATHROOM = [
    ("q", (4.09, 0.46),  (2.32, 0.46)),        # W1
    ("r", (2.32, 0.46),  (2.32, -1.11)),       # W2
    ("s", (2.32, -1.11), (4.09, -1.11)),       # W3
    ("t", (4.09, -1.11), (4.09, 0.46)),        # W4, corner to corner THROUGH the door
]
DIM_BATHROOM_OPEN = [("u", (4.09, -0.32), (4.09, 0.46))]
DIM_BATHROOM_DIAG: list = []  # same


def draw_dims(ax, segments, openings, diagonals, title):
    for _lbl, a, b in segments:
        ax.plot([a[0], b[0]], [a[1], b[1]], color=WALL, lw=5, solid_capstyle="butt", zorder=2)
    for _lbl, a, b in openings:
        ax.plot([a[0], b[0]], [a[1], b[1]], color=OPENING, lw=5, solid_capstyle="butt", zorder=3)
    for _lbl, a, b in diagonals:
        ax.plot([a[0], b[0]], [a[1], b[1]], color=TAPE, lw=1.4, ls=(0, (6, 4)), zorder=4)

    def badge(lbl, a, b, fc, nudge=(0.0, 0.0), frac=0.5):
        mx = a[0] + (b[0] - a[0]) * frac + nudge[0]
        my = a[1] + (b[1] - a[1]) * frac + nudge[1]
        ax.annotate(lbl, (mx, my), color="white", fontsize=12, weight="bold", ha="center",
                    va="center", zorder=9,
                    bbox=dict(boxstyle="circle,pad=0.30", fc=fc, ec="white", lw=1.6))

    nudges = {"a": (0.30, 0), "b": (0, -0.26), "c": (0.30, 0.16), "d": (0, -0.26),
              "e": (-0.30, 0), "f": (-1.40, 0.26), "q": (0, -0.24), "r": (0.26, 0),
              "s": (0, 0.24), "t": (-0.26, 0)}
    for lbl, a, b in segments:
        badge(lbl, a, b, WALL, nudges.get(lbl, (0.0, 0.0)))
    for lbl, a, b in openings:
        badge(lbl, a, b, OPENING)
    for n, (lbl, a, b) in enumerate(diagonals):
        badge(lbl, a, b, TAPE, frac=0.30 if n == 0 else 0.70)

    ax.set_title(title, fontsize=12, weight="bold", color=WALL, pad=14)
    ax.set_aspect("equal")
    ax.margins(0.20)
    ax.axis("off")


def main_dims() -> int:
    fig, axes = plt.subplots(1, 2, figsize=(14.0, 8.6),
                             gridspec_kw={"width_ratios": [1.0, 0.82]})
    draw_dims(axes[0], DIM_BEDROOM, DIM_BEDROOM_OPEN, DIM_BEDROOM_DIAG,
              "BEDROOM — write each length in cm")
    draw_dims(axes[1], DIM_BATHROOM, DIM_BATHROOM_OPEN, DIM_BATHROOM_DIAG,
              "BATHROOM — write each length in cm")

    axes[0].annotate("BUILT-IN CUPBOARD\nb = front,  c = end", (-1.55, 1.49),
                     color=WALL, fontsize=8, style="italic", ha="center", va="center", zorder=6,
                     bbox=dict(boxstyle="round,pad=0.3", fc="#eef1f4", ec=WALL, lw=0.8))
    axes[0].annotate("g → BATHROOM", (0.08, -2.58), color=OPENING, fontsize=8.5, weight="bold",
                     ha="center", va="top")
    axes[0].annotate("i — MAIN DOORWAY", (0.71, 1.95), color=OPENING, fontsize=9, weight="bold",
                     ha="center", va="bottom")

    legend = (
        "dark circle = wall, corner to corner      red circle = opening, CLEAR WIDTH\n"
        "f and t run corner to corner STRAIGHT THROUGH the doorway in that wall.\n"
        "\n"
        "NOT on the drawing, and still needed -- the ceiling, in TWO PARTS per spot:\n"
        "  m + n = bedroom spot 1 (floor-to-seat, then seat-to-ceiling)\n"
        "  o + p = bedroom spot 2, at least 1 m away      y + z = bathroom\n"
        "\n"
        "No diagonals: head_to_head reads them and does not use them.\n"
        "ALL VALUES IN CENTIMETRES."
    )
    fig.text(0.5, 0.165, legend, ha="center", va="top", fontsize=8.8, color=WALL,
             family="monospace",
             bbox=dict(boxstyle="round,pad=0.6", fc="#f6f7f9", ec=WALL, lw=0.8))
    fig.suptitle("Dimension sheet — one letter per measurement, all in cm",
                 fontsize=13, weight="bold", color=WALL, y=0.97)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.90, bottom=0.235, wspace=0.05)
    out_png = ROOT / "data" / "own" / "dimensions.png"
    fig.savefig(out_png, dpi=170)
    fig.savefig(ROOT / "data" / "own" / "dimensions.pdf")
    plt.close(fig)
    print(f"wrote {out_png.relative_to(ROOT)}")
    return 0
